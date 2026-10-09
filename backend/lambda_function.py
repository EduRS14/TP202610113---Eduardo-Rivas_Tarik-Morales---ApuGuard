"""
lambda_function.py - APU GUARD
================================
Funcion AWS Lambda que convierte los resultados .npz de SageMaker
en imagenes PNG visualizables para el frontend.

Trigger: S3 ObjectCreated en sagemaker-outputs/*.npz
Salida : sagemaker-visualizations/captura_{id}/parche_{fila}_{col}_rgb.png
         sagemaker-visualizations/captura_{id}/parche_{fila}_{col}_mask.png

Layers requeridas: numpy + Pillow
  - Opcion A: AWS SDK for pandas (incluye numpy)
  - Opcion B: KLayers publico con numpy+pillow
  - Opcion C: Layer personalizada (pip install numpy pillow -t python/ -> zip)

Permisos IAM requeridos en el rol de ejecucion:
  s3:GetObject  sobre apuguard-datalake-prod
  s3:PutObject  sobre apuguard-datalake-prod
"""

import io
import json

import boto3
import numpy as np
from PIL import Image

s3 = boto3.client("s3")


def lambda_handler(event, context):
    try:
        bucket     = event["Records"][0]["s3"]["bucket"]["name"]
        output_key = event["Records"][0]["s3"]["object"]["key"]
        # Ej: "sagemaker-outputs/captura_15/parche_2_4.npz"

        # -- 1. Derivar rutas por espejo --
        input_key = output_key.replace("outputs", "inputs").replace(".npz", ".npy")
        # Ej: "sagemaker-inputs/captura_15/parche_2_4.npy"

        base_name = output_key.replace("sagemaker-outputs/", "").replace(".npz", "")
        # Ej: "captura_15/parche_2_4"

        # -- 2. Descargar .npz (resultado SageMaker) --
        response_out = s3.get_object(Bucket=bucket, Key=output_key)
        npz_data     = np.load(io.BytesIO(response_out["Body"].read()))

        # squeeze() total: [1, 1, 128, 128] -> [128, 128]
        probability = npz_data["probability"].squeeze()

        # -- 3. Descargar .npy (tensor de entrada normalizado) --
        response_in  = s3.get_object(Bucket=bucket, Key=input_key)
        input_tensor = np.load(io.BytesIO(response_in["Body"].read()))
        # Shape: [1, 9, 128, 128]

        # -- 4. Stretch percentil p2-p98 para canales z-score --
        def stretch(canal):
            p2, p98     = np.percentile(canal, (2, 98))
            canal_clip  = np.clip(canal, p2, p98)
            canal_norm  = (canal_clip - p2) / (p98 - p2 + 1e-8) * 255
            return canal_norm.astype(np.uint8)

        r = stretch(input_tensor[0, 2, :, :])   # ch2 = Red
        g = stretch(input_tensor[0, 1, :, :])   # ch1 = Green
        b = stretch(input_tensor[0, 0, :, :])   # ch0 = Blue

        # -- 5. Imagen RGB --
        rgb_stack = np.stack((r, g, b), axis=-1)
        img_rgb   = Image.fromarray(rgb_stack, "RGB")

        # -- 6. Capa termica de la IA (rojo con alpha = probabilidad) --
        alpha_channel = (probability * 255).astype(np.uint8)
        red_channel   = np.full((128, 128), 255, dtype=np.uint8)
        zero_channel  = np.zeros((128, 128), dtype=np.uint8)

        mask_rgba = np.stack(
            (red_channel, zero_channel, zero_channel, alpha_channel), axis=-1
        )
        img_mask = Image.fromarray(mask_rgba, "RGBA")

        # -- 7. Serializar y subir a S3 --
        rgb_buffer = io.BytesIO()
        img_rgb.save(rgb_buffer, format="PNG")
        rgb_buffer.seek(0)

        mask_buffer = io.BytesIO()
        img_mask.save(mask_buffer, format="PNG")
        mask_buffer.seek(0)

        s3.put_object(
            Bucket=bucket,
            Key=f"sagemaker-visualizations/{base_name}_rgb.png",
            Body=rgb_buffer,
            ContentType="image/png",
        )
        s3.put_object(
            Bucket=bucket,
            Key=f"sagemaker-visualizations/{base_name}_mask.png",
            Body=mask_buffer,
            ContentType="image/png",
        )

        return {
            "statusCode": 200,
            "body": json.dumps(f"PNGs generados para {base_name}"),
        }

    except Exception as e:
        print(f"Error procesando {output_key}: {e}")
        raise e
