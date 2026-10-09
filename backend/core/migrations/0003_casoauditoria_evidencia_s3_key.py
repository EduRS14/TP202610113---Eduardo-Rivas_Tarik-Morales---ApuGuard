from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_alter_casoauditoria_estado_caso_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='casoauditoria',
            name='evidencia_s3_key',
            field=models.CharField(
                blank=True,
                max_length=500,
                help_text='Ruta S3 de la foto de evidencia subida por el tecnico (jpg/png).',
            ),
        ),
    ]
