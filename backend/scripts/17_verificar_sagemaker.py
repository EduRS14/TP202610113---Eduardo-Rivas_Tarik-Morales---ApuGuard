"""
17_verificar_sagemaker.py
==========================
Inspecciona la configuracion del endpoint SageMaker:
  - Estado del endpoint
  - Modelo desplegado y su ModelDataUrl (model.tar.gz)
  - Configuracion Async: output S3, SNS success/error
  - Fecha de creacion de cada recurso

Uso (dentro del contenedor web):
    docker compose exec web python /app/scripts/17_verificar_sagemaker.py

Uso local (sin Django; usa las credenciales del perfil de AWS CLI):
    python backend/scripts/17_verificar_sagemaker.py
"""
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _template_python import load_env


def cargar_config():
    """settings de Django si el entorno lo permite; si no, el .env directo."""
    try:
        from _template_python import setup
        setup()
        import django
        django.setup()
        from django.conf import settings
        return (settings.AWS_REGION_NAME, settings.AWS_SAGEMAKER_ENDPOINT_NAME,
                settings.AWS_S3_BUCKET_NAME, "Django")
    except Exception as exc:
        load_env()
        region = os.environ.get("AWS_REGION_NAME", "us-east-1")
        endpoint = os.environ.get("SAGEMAKER_ENDPOINT")
        bucket = os.environ.get("AWS_S3_BUCKET_NAME") or os.environ.get("AWS_S3_BUCKET")
        return region, endpoint, bucket, f"env local (.env, sin Django: {type(exc).__name__})"


import boto3


def main():
    region, endpoint_name, bucket, origen = cargar_config()
    if not endpoint_name:
        print("[ERROR] SAGEMAKER_ENDPOINT no esta definido en backend/.env")
        return 1
    sm = boto3.client("sagemaker", region_name=region)

    print("=" * 70)
    print(" APU GUARD - Verificar Endpoint SageMaker")
    print("=" * 70)
    print(f"Region:   {region}")
    print(f"Endpoint: {endpoint_name}")
    print(f"Bucket:   {bucket}")
    print()

    # ── 1. Endpoint ─────────────────────────────────────────────────────────
    try:
        ep = sm.describe_endpoint(EndpointName=endpoint_name)
        print(f"[1] Endpoint: {ep['EndpointName']}")
        print(f"    Estado:             {ep['EndpointStatus']}")
        print(f"    Config actual:      {ep.get('EndpointConfigName', 'N/A')}")
        print(f"    Creado:             {ep['CreationTime'].strftime('%Y-%m-%d %H:%M')}")
        print(f"    Ultima actualizacion: {ep['LastModifiedTime'].strftime('%Y-%m-%d %H:%M')}")
        config_name = ep.get("EndpointConfigName")
    except Exception as e:
        print(f"    [ERROR] No se pudo obtener el endpoint: {e}")
        return 1

    if not config_name:
        print("    [WARN] El endpoint no tiene configuracion asociada.")
        return 1

    # ── 2. Endpoint Config ──────────────────────────────────────────────────
    try:
        cfg = sm.describe_endpoint_config(EndpointConfigName=config_name)
        print(f"\n[2] Endpoint Config: {cfg['EndpointConfigName']}")
        print(f"    Creado: {cfg['CreationTime'].strftime('%Y-%m-%d %H:%M')}")

        variants = cfg.get("ProductionVariants", [])
        model_name = variants[0]["ModelName"] if variants else "N/A"
        instance_type = variants[0].get("InstanceType", "N/A") if variants else "N/A"
        print(f"    Modelo:         {model_name}")
        print(f"    Instancia:      {instance_type}")

        # Async config
        async_cfg = cfg.get("AsyncInferenceConfig", {})
        if async_cfg:
            s3_output = async_cfg.get("OutputConfig", {}).get("S3OutputPath", "N/A")
            sns_success = async_cfg.get("OutputConfig", {}).get("NotificationConfig", {}).get("SuccessTopic", "N/A")
            sns_error   = async_cfg.get("OutputConfig", {}).get("NotificationConfig", {}).get("ErrorTopic", "N/A")
            print(f"    Output S3:      {s3_output}")
            print(f"    SNS Success:    {sns_success}")
            print(f"    SNS Error:      {sns_error}")
        else:
            print("    [WARN] Sin AsyncInferenceConfig (real-time, no async).")
    except Exception as e:
        print(f"    [ERROR] No se pudo obtener la config: {e}")
        model_name = None

    # ── 3. Model ────────────────────────────────────────────────────────────
    if model_name:
        try:
            mdl = sm.describe_model(ModelName=model_name)
            print(f"\n[3] Model: {mdl['ModelName']}")
            print(f"    ARN:       {mdl['ModelArn']}")
            print(f"    Creado:    {mdl['CreationTime'].strftime('%Y-%m-%d %H:%M')}")
            containers = mdl.get("PrimaryContainer", {})
            image = containers.get("Image", "N/A")
            data_url = containers.get("ModelDataUrl", "N/A")
            print(f"    Container: {image}")
            print(f"    Data URL:  {data_url}")

            # Verificar si el archivo existe en S3
            if data_url.startswith("s3://"):
                s3_path = data_url.replace("s3://", "")
                if "/" in s3_path:
                    s3_bucket, s3_key = s3_path.split("/", 1)
                else:
                    s3_bucket = s3_path
                    s3_key = ""
                try:
                    s3 = boto3.client("s3", region_name=region)
                    obj = s3.head_object(Bucket=s3_bucket, Key=s3_key)
                    size_mb = obj["ContentLength"] / (1024 * 1024)
                    print(f"    Tamano:    {size_mb:.1f} MB")
                    print(f"    Existe:    SI")
                    if size_mb < 1:
                        print(f"    [WARN] ModelDataUrl apunta a un archivo MINUSCULO ({size_mb:.1f} MB).")
                        print(f"           Probable razon de que el modelo devuelva todo ceros.")
                    else:
                        print(f"    [OK] Archivo de tamano razonable ({size_mb:.1f} MB).")
                except Exception:
                    print(f"    Existe:    NO (404)")
                    print(f"    [ERROR] ModelDataUrl apunta a un archivo que NO EXISTE en S3.")
                    print(f"            El modelo desplegado esta vacio -> devuelve todo ceros.")
        except Exception as e:
            print(f"\n[3] Model: [ERROR] No se pudo obtener: {e}")

    # ── 4. Verdict ──────────────────────────────────────────────────────────
    print("\n" + "-" * 70)
    print("[VEREDICTO]")
    print("-" * 70)
    if model_name:
        print(f"  El modelo '{model_name}' esta activo en el endpoint.")
        print(f"  Si la salida del modelo es todo ceros, verifica que el Data URL")
        print(f"  apunte al model.tar.gz CORRECTO de entrenamiento,")
        print(f"  y que el archivo pese al menos 10-50 MB.")
        print(f"")
        print(f"  Si necesitas re-desplegar con otro modelo:")
        print(f"    scripts\\18_redeploy_sagemaker.bat s3://TU-BUCKET/path/model.tar.gz")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
