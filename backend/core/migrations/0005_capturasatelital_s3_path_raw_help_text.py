from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_perfilanalista'),
    ]

    operations = [
        migrations.AlterField(
            model_name='capturasatelital',
            name='s3_path_raw',
            field=models.CharField(
                help_text='Ruta S3 del raster GeoTIFF crudo descargado (Sentinel-2).',
                max_length=500,
            ),
        ),
    ]
