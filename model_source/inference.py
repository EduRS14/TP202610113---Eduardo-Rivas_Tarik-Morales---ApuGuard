"""
inference.py
============
Entry point de SageMaker para APU GUARD - HRNet-w18 + Monte Carlo Dropout.

Contrato SageMaker PyTorch:
  - model_fn(model_dir)           -> model
  - input_fn(body, content_type)  -> tensor
  - predict_fn(input_data, model) -> dict
  - output_fn(prediction, accept) -> bytes

Inferencia:
  - 20 pases estocasticos con Dropout2d activo (Monte Carlo Dropout)
  - Threshold optimo: 0.30 (optimizado en val set, Tambopata 2024)
  - Retorna .npz con: mask, probability, entropy

Normalizacion de entrada:
  SageMaker recibe los parches YA NORMALIZADOS por Django.
  Django aplica z-score a ch0-5 usando mean/std del composite completo.
  ch6-8 (distancias) llegan estirados con el percentil P2-P98 por canal
  (mismo preprocesamiento congelado del dataset evaluado) a [-1, 1].
  No se aplica ningun desplazamiento adicional a los logits.

Referencia MCD: Chamorro-Martinez et al., ISPRS J. Photogramm. Remote Sens., 2024
"""

import io
import os
import json
import torch
import numpy as np
from hrnet import get_hrnet_w18

# -- Constantes --
THRESHOLD        = 0.30
N_MCD_PASSES     = 20
CHECKPOINT_NAME  = "hrnet_final_seed42.pth"
DROPOUT_P        = 0.20
DROPOUT_POSITION = "before_head"


def enable_dropout(model):
    """Activa Dropout2d en modo train mientras el resto permanece en eval (MCD)."""
    model.eval()
    for m in model.modules():
        if isinstance(m, (torch.nn.Dropout, torch.nn.Dropout2d)):
            m.train()


def model_fn(model_dir):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model  = get_hrnet_w18(
        in_channels=9,
        out_channels=1,
        dropout_p=DROPOUT_P,
        dropout_position=DROPOUT_POSITION,
    )

    model_path = os.path.join(model_dir, CHECKPOINT_NAME)
    if os.path.exists(model_path):
        model.load_state_dict(
            torch.load(model_path, map_location=device, weights_only=True)
        )
        print(f"[APU GUARD] Pesos cargados desde: {model_path}")
    else:
        print(f"[APU GUARD] ADVERTENCIA: {model_path} no encontrado. "
              f"Usando pesos aleatorios (solo valido para pruebas de forma).")

    enable_dropout(model)
    model = model.to(device)

    n_params = sum(p.numel() for p in model.parameters())
    print(f"[APU GUARD] HRNet-w18 + MCD x{N_MCD_PASSES} listo | "
          f"Device: {device} | Parametros: {n_params:,}")
    return model


def input_fn(request_body, content_type="application/x-npy"):
    """
    Deserializa el cuerpo de la peticion a tensor PyTorch.
    Soporta: application/x-npy (np.save) y application/json.
    Shape esperado: [B, 9, 128, 128] float32 ya normalizado.
    """
    if content_type == "application/x-npy":
        arr = np.load(io.BytesIO(request_body))
    elif content_type == "application/json":
        arr = np.array(json.loads(request_body), dtype=np.float32)
    else:
        raise ValueError(
            f"Content-type no soportado: {content_type}. "
            f"Use 'application/x-npy' o 'application/json'."
        )
    return torch.from_numpy(arr).float()


def predict_fn(input_data, model):
    """
    Ejecuta N_MCD_PASSES inferencias estocasticas y calcula:
      mask        : binaria {0.0, 1.0} con threshold=0.30
      probability : probabilidad media MCD por pixel
      entropy     : entropia predictiva por pixel [0, ln(2)]

    Precondicion: parche ya normalizado (z-score global en ch0-5,
    stretch P2-P98 -> [-1, 1] en ch6-8).
    Los logits NO se desplazan: el umbral 0.30 se calibro sobre
    estos mismos logits.
    """
    device = next(model.parameters()).device
    input_data = input_data.to(device)

    passes = []
    with torch.no_grad():
        for _ in range(N_MCD_PASSES):
            logits = model(input_data)
            prob   = torch.sigmoid(logits)
            passes.append(prob)

    stacked = torch.stack(passes, dim=0)       # [N, B, 1, 128, 128]
    mu      = stacked.float().mean(dim=0)      # [B, 1, 128, 128]

    eps     = 1e-7
    entropy = (
        -mu * torch.log(mu + eps)
        - (1.0 - mu) * torch.log(1.0 - mu + eps)
    )

    mask = (mu > THRESHOLD).float()

    return {
        "mask":        mask.cpu().numpy().astype(np.float32),
        "probability": mu.cpu().numpy().astype(np.float32),
        "entropy":     entropy.cpu().numpy().astype(np.float32),
    }


def output_fn(prediction, accept="application/x-npz"):
    """
    Serializa la salida como .npz comprimido.

    Django lo carga con:
      data = np.load(io.BytesIO(response_body))
      mask, prob, entropy = data["mask"], data["probability"], data["entropy"]
    """
    buffer = io.BytesIO()
    np.savez_compressed(
        buffer,
        mask=prediction["mask"],
        probability=prediction["probability"],
        entropy=prediction["entropy"],
    )
    buffer.seek(0)
    return buffer.read(), "application/x-npz"
