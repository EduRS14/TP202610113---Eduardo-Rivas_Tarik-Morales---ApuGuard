"""
hrnet.py
========
Arquitectura HRNet-w18 adaptada para APU GUARD.

Entrada : tensor de 9 canales [B, 9, 128, 128]
           ch0=Blue, ch1=Green, ch2=Red, ch3=NIR, ch4=NDWI,
           ch5=SAVI, ch6=dist_deforest, ch7=dist_mining, ch8=dist_rivers
Salida  : logits [B, 1, 128, 128]  (aplicar sigmoid para obtener probabilidades)

MCD     : Dropout2d configurable en seg_head; activar durante inferencia MCD.

Compatible con la arquitectura de entrenamiento en src/benchmark_models.py.
Configuracion mejorada: dropout_p=0.20, dropout_position="before_head".
Este archivo define el modelo; MCDx20 y el umbral se aplican en inference.py.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
import timm


class HRNetSegmentation(nn.Module):
    def __init__(
        self,
        encoder_name: str = "hrnet_w18_small_v2",
        in_channels: int = 9,
        num_classes: int = 1,
        pretrained: bool = False,
        dropout_p: float = 0.1,
        dropout_position: str = "original",
    ):
        super().__init__()

        if dropout_position not in ("original", "before_head"):
            raise ValueError(
                "dropout_position debe ser original o before_head"
            )
        self.dropout_position = dropout_position

        self.encoder = timm.create_model(
            encoder_name,
            pretrained=pretrained,
            in_chans=in_channels,
            features_only=True,
        )

        # Inferir canales del encoder con una entrada de ejemplo.
        with torch.no_grad():
            dummy = torch.zeros(1, in_channels, 128, 128)
            feats = self.encoder(dummy)
            self.encoder_channels = [f.shape[1] for f in feats[:4]]

        # Alinear c2, c3 y c4 con la resolucion espacial de c1.
        self.up2 = nn.Sequential(
            nn.Upsample(
                scale_factor=2,
                mode="bilinear",
                align_corners=True,
            ),
            nn.Conv2d(
                self.encoder_channels[1],
                self.encoder_channels[1],
                kernel_size=3,
                padding=1,
                bias=False,
            ),
            nn.GroupNorm(
                num_groups=8,
                num_channels=self.encoder_channels[1],
            ),
            nn.ReLU(inplace=True),
        )

        self.up3 = nn.Sequential(
            nn.Upsample(
                scale_factor=4,
                mode="bilinear",
                align_corners=True,
            ),
            nn.Conv2d(
                self.encoder_channels[2],
                self.encoder_channels[2],
                kernel_size=3,
                padding=1,
                bias=False,
            ),
            nn.GroupNorm(
                num_groups=8,
                num_channels=self.encoder_channels[2],
            ),
            nn.ReLU(inplace=True),
        )

        self.up4 = nn.Sequential(
            nn.Upsample(
                scale_factor=8,
                mode="bilinear",
                align_corners=True,
            ),
            nn.Conv2d(
                self.encoder_channels[3],
                self.encoder_channels[3],
                kernel_size=3,
                padding=1,
                bias=False,
            ),
            nn.GroupNorm(
                num_groups=8,
                num_channels=self.encoder_channels[3],
            ),
            nn.ReLU(inplace=True),
        )

        total_ch = sum(self.encoder_channels)
        head_ch = 256

        # Conservar el orden registrado mantiene los nombres del checkpoint.
        # La posicion efectiva del dropout se decide en forward.
        self.seg_head = nn.Sequential(
            nn.Conv2d(
                total_ch,
                head_ch,
                kernel_size=1,
                bias=False,
            ),
            nn.GroupNorm(num_groups=8, num_channels=head_ch),
            nn.ReLU(inplace=True),
            nn.Conv2d(
                head_ch,
                head_ch,
                kernel_size=3,
                padding=1,
                bias=False,
            ),
            nn.GroupNorm(num_groups=8, num_channels=head_ch),
            nn.ReLU(inplace=True),
            nn.Dropout2d(p=dropout_p),
            nn.Conv2d(head_ch, num_classes, kernel_size=1),
        )

        self._init_decoder_weights()

    def _init_decoder_weights(self):
        for block in (self.seg_head, self.up2, self.up3, self.up4):
            for module in block.modules():
                if isinstance(module, nn.Conv2d):
                    nn.init.kaiming_normal_(
                        module.weight,
                        mode="fan_in",
                        nonlinearity="relu",
                    )
                    if module.bias is not None:
                        nn.init.constant_(module.bias, 0)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        feats = self.encoder(x)
        c1, c2, c3, c4 = feats[0], feats[1], feats[2], feats[3]

        c2_up = self.up2(c2)
        c3_up = self.up3(c3)
        c4_up = self.up4(c4)

        target_size = c1.shape[2:]

        if c2_up.shape[2:] != target_size:
            c2_up = F.interpolate(
                c2_up,
                size=target_size,
                mode="bilinear",
                align_corners=True,
            )

        if c3_up.shape[2:] != target_size:
            c3_up = F.interpolate(
                c3_up,
                size=target_size,
                mode="bilinear",
                align_corners=True,
            )

        if c4_up.shape[2:] != target_size:
            c4_up = F.interpolate(
                c4_up,
                size=target_size,
                mode="bilinear",
                align_corners=True,
            )

        x = torch.cat([c1, c2_up, c3_up, c4_up], dim=1)

        if self.dropout_position == "before_head":
            # Aplicar el mismo dropout antes de la primera convolucion
            # de la cabeza, conservando los nombres de todas las capas.
            for index in (6, 0, 1, 2, 3, 4, 5, 7):
                x = self.seg_head[index](x)
        else:
            x = self.seg_head(x)

        if x.shape[2:] != (128, 128):
            x = F.interpolate(
                x,
                size=(128, 128),
                mode="bilinear",
                align_corners=True,
            )

        return x


def get_hrnet_w18(
    in_channels: int = 9,
    out_channels: int = 1,
    dropout_p: float = 0.1,
    dropout_position: str = "original",
) -> HRNetSegmentation:
    """
    Instancia HRNet-w18 para cargar un checkpoint de APU GUARD.

    Args:
        in_channels: numero de canales de entrada.
        out_channels: numero de clases de salida.
        dropout_p: probabilidad de dropout.
        dropout_position: original o before_head.

    La configuracion mejorada utiliza:
        dropout_p=0.20
        dropout_position="before_head"
    """
    return HRNetSegmentation(
        encoder_name="hrnet_w18_small_v2",
        in_channels=in_channels,
        num_classes=out_channels,
        pretrained=False,
        dropout_p=dropout_p,
        dropout_position=dropout_position,
    )


if __name__ == "__main__":
    # Comprobacion de dimensiones; no carga pesos ni evalua metricas.
    model = get_hrnet_w18(
        dropout_p=0.20,
        dropout_position="before_head",
    )
    model.eval()

    dummy = torch.randn(2, 9, 128, 128)

    with torch.no_grad():
        out = model(dummy)

    n_params = sum(p.numel() for p in model.parameters())

    print("HRNet-w18 APU GUARD")
    print(f"  Parametros: {n_params:,}")
    print(f"  Input: {tuple(dummy.shape)}")
    print(f"  Output: {tuple(out.shape)}")

    assert out.shape == (2, 1, 128, 128), (
        f"Shape inesperado: {out.shape}"
    )
    print("Comprobacion de dimensiones correcta.")