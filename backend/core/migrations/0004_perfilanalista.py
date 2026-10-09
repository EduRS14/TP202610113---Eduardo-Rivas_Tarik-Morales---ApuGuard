from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_casoauditoria_evidencia_s3_key'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PerfilAnalista',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('user', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='analista_perfil',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('sectores', models.ManyToManyField(
                    blank=True,
                    related_name='analistas',
                    to='core.sectorreserva',
                )),
            ],
            options={
                'verbose_name': 'Perfil Analista',
                'verbose_name_plural': 'Perfiles Analista',
            },
        ),
    ]
