"""
18_redeploy_sagemaker.py
=========================
Crea un nuevo modelo SageMaker y actualiza el endpoint para que use
el model.tar.gz correcto.

Preserva la configuracion Async existente (output S3, SNS, instancia).

Uso (dentro del contenedor web):
    docker compose exec web python /app/scripts/18_redeploy_sagemaker.py \
        s3://apuguard-datalake-prod/models/hrnet/model.tar.gz

Uso local (sin Django; usa las credenciales del perfil de AWS CLI):
    python backend/scripts/18_redeploy_sagemaker.py s3://.../model.tar.gz

Requiere que el archivo model.tar.gz exista en el path S3 indicado.
"""
import os
import sys
import time
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
        return settings.AWS_REGION_NAME, settings.AWS_SAGEMAKER_ENDPOINT_NAME, "Django"
    except Exception as exc:
        load_env()
        region = os.environ.get("AWS_REGION_NAME", "us-east-1")
        endpoint = os.environ.get("SAGEMAKER_ENDPOINT")
        return region, endpoint, f"env local (.env, sin Django: {type(exc).__name__})"


import boto3


def main():
    if len(sys.argv) < 2:
        print("Uso: python 18_redeploy_sagemaker.py s3://BUCKET/PATH/model.tar.gz")
        print()
        print("Ejemplo:")
        print("  python 18_redeploy_sagemaker.py s3://apuguard-datalake-prod/models/hrnet/model.tar.gz")
        return 1

    new_data_url = sys.argv[1]
    if not new_data_url.startswith("s3://"):
        print("[ERROR] El path debe comenzar con s3://")
        return 1

    region, endpoint_name, origen = cargar_config()
    if not endpoint_name:
        print("[ERROR] No se ha podido determinar el nombre del endpoint")
        print("        (SAGEMAKER_ENDPOINT en backend/.env o settings).")
        return 1
    sm = boto3.client("sagemaker", region_name=region)
    s3 = boto3.client("s3", region_name=region)
    print(f"Configuracion cargada desde: {origen}")
    print(f"  region={region}  endpoint={endpoint_name}")

    # ── Verificar que el archivo existe ─────────────────────────────────────
    s3_path = new_data_url.replace("s3://", "")
    if "/" in s3_path:
        s3_bucket, s3_key = s3_path.split("/", 1)
    else:
        s3_bucket = s3_path
        s3_key = ""

    try:
        obj = s3.head_object(Bucket=s3_bucket, Key=s3_key)
        size_mb = obj["ContentLength"] / (1024 * 1024)
        print(f"[OK] Archivo encontrado: {new_data_url} ({size_mb:.1f} MB)")
    except Exception as e:
        print(f"[ERROR] Archivo no encontrado en {new_data_url}: {e}")
        return 1

    # ── 1. Obtener config actual ────────────────────────────────────────────
    print("Obteniendo configuracion actual del endpoint...")
    try:
        ep = sm.describe_endpoint(EndpointName=endpoint_name)
        old_config_name = ep.get("EndpointConfigName")
        cfg = sm.describe_endpoint_config(EndpointConfigName=old_config_name)
        variants = cfg.get("ProductionVariants", [])
        instance_type = variants[0]["InstanceType"]
        async_cfg = cfg.get("AsyncInferenceConfig", {})
    except Exception as e:
        print(f"[ERROR] No se pudo obtener la config actual: {e}")
        return 1

    # ── 2. Determinar nombres versionados ───────────────────────────────────
    import re
    existing_models = [
        m["ModelName"] for m in
        sm.list_models(NameContains="apuguard-hrnet-v", SortBy="CreationTime", SortOrder="Descending")["Models"]
    ]
    versiones = []
    for m in existing_models:
        match = re.search(r"apuguard-hrnet-v(\d+)", m)
        if match:
            versiones.append(int(match.group(1)))

    next_ver = max(versiones) + 1 if versiones else 3
    new_model_name = f"apuguard-hrnet-v{next_ver}"
    new_config_name = f"apuguard-endpoint-config-v{next_ver}"

    # ── 3. Resumen antes de continuar ───────────────────────────────────────
    print()
    print("=" * 70)
    print(" RESUMEN DE LA OPERACION")
    print("=" * 70)
    print(f"  Endpoint:        {endpoint_name} ({ep['EndpointStatus']})")
    print(f"  Instancia:       {instance_type}")
    print(f"  Config actual:   {old_config_name}")
    print(f"  Modelo actual:   {variants[0]['ModelName']}")
    print()
    print(f"  Nuevo modelo:    {new_model_name}")
    print(f"  Nueva config:    {new_config_name}")
    print(f"  Nuevo Data URL:  {new_data_url}")
    print(f"  Tamano archivo:  {size_mb:.1f} MB")
    print(f"  Output S3 (async): {async_cfg.get('OutputConfig', {}).get('S3OutputPath', 'N/A')}")
    print("=" * 70)
    print()

    confirm = input("Confirmar re-despliegue? (s/n): ").strip().lower()
    if confirm not in ("s", "si", "y", "yes"):
        print("Cancelado.")
        return 0

    # ── 3.5. Obtener el ARN del rol desde el modelo actual ──────────────────
    old_model_name = variants[0]["ModelName"]
    try:
        old_mdl = sm.describe_model(ModelName=old_model_name)
        role_arn = old_mdl.get("ExecutionRoleArn", "")
    except Exception:
        role_arn = ""

    if not role_arn:
        # Intentar obtenerlo de IAM
        try:
            iam = boto3.client("iam", region_name=region)
            roles = iam.list_roles(PathPrefix="/")["Roles"]
            for r in roles:
                if "SageMaker" in r["RoleName"] and "ApuGuard" in r["RoleName"]:
                    role_arn = r["Arn"]
                    break
        except Exception:
            pass

    if not role_arn:
        print("[ERROR] No se pudo obtener el ExecutionRoleArn del modelo existente.")
        print("        Verifica en AWS Console el rol de ejecucion del modelo.")
        return 1

    print(f"    Rol de ejecucion: {role_arn.split('/')[-1]}")

    # ── 3.6. Determinar imagen del contenedor ──────────────────────────────
    # SageMaker requiere PrimaryContainer.Image.
    # Usamos PyTorch inference GPU oficial de AWS DLC.
    account_id = "763104351884"
    container_image = (
        f"{account_id}.dkr.ecr.{region}.amazonaws.com/"
        f"pytorch-inference:2.0.1-gpu-py310"
    )
    print(f"    Container:     {container_image.split('/')[-1]} (PyTorch 2.0.1 GPU)")

    # ── 4. Crear nuevo modelo ───────────────────────────────────────────────
    print(f"\n[1/3] Creando modelo: {new_model_name}")
    sm.create_model(
        ModelName=new_model_name,
        ExecutionRoleArn=role_arn,
        PrimaryContainer={
            "Image": container_image,
            "ModelDataUrl": new_data_url,
        },
    )
    print(f"  [OK] Modelo {new_model_name} creado.")

    # ── 5. Crear nueva endpoint config (preservando async settings) ─────────
    print(f"\n[2/3] Creando config: {new_config_name}")
    endpoint_config_kwargs = {
        "EndpointConfigName": new_config_name,
        "ProductionVariants": [
            {
                "VariantName":      "variant-name-1",
                "ModelName":         new_model_name,
                "InstanceType":      instance_type,
                "InitialInstanceCount": 1,
            }
        ],
    }
    if async_cfg:
        endpoint_config_kwargs["AsyncInferenceConfig"] = async_cfg

    sm.create_endpoint_config(**endpoint_config_kwargs)
    print(f"  [OK] Config {new_config_name} creada.")

    # ── 6. Actualizar endpoint ──────────────────────────────────────────────
    print(f"\n[3/3] Actualizando endpoint: {endpoint_name}")
    sm.update_endpoint(
        EndpointName=endpoint_name,
        EndpointConfigName=new_config_name,
    )
    print(f"  [OK] Actualizacion iniciada.")

    # ── 7. Esperar a que el endpoint este listo ─────────────────────────────
    print(f"\nEsperando a que el endpoint pase a InService...")
    for i in range(60):
        time.sleep(10)
        ep = sm.describe_endpoint(EndpointName=endpoint_name)
        status = ep["EndpointStatus"]
        elapsed = (i + 1) * 10
        print(f"  [{elapsed}s] Estado: {status}")
        if status == "InService":
            print(f"\n[OK] Endpoint {endpoint_name} en servicio con el nuevo modelo.")
            print(f"     Modelo:  {new_model_name}")
            print(f"     Config:  {new_config_name}")
            print(f"     Data URL: {new_data_url}")
            try:
                v = ep["ProductionVariants"][0]
                print(f"     Instancias: Current={v.get('CurrentInstanceCount')} "
                      f"Desired={v.get('DesiredInstanceCount')}")
            except Exception:
                pass
            print(f"\n  Ya puedes lanzar una quincena de prueba:")
            print(f"    scripts\\04_lanzar_quincena.bat")
            print(f"\n  [AVISO] La config nueva usa InitialInstanceCount=1: desde aqui el")
            print(f"          endpoint factura ml.g4dn.xlarge (~0.74 USD/h). Cuando termine")
            print(f"          la quincena, bajalo a Desired=0:")
            print(f"            aws sagemaker update-endpoint-weights-and-capacities \\")
            print(f"              --endpoint-name {endpoint_name} --region {region} \\")
            print(f"              --desired-weights-and-capacities VariantName=variant-name-1,DesiredInstanceCount=0")
            print(f"          (solo el numero de instancias: peso y instancias no se pueden")
            print(f"          cambiar en la misma llamada). Y Desired=1 ANTES de la proxima")
            print(f"          quincena.")
            return 0
        elif status == "Failed":
            print(f"\n[ERROR] El endpoint fallo al actualizarse.")
            print(f"     Revisa CloudWatch: /aws/sagemaker/Endpoints/{endpoint_name}")
            return 1

    print(f"\n[WARN] Timeout (10 min). El endpoint sigue en estado '{ep['EndpointStatus']}'.")
    print(f"     Monitorea en AWS Console: SageMaker > Endpoints > {endpoint_name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
