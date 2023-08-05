# Generated by Django 2.2.23 on 2021-09-15 14:35

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('django_cog', '0013_task_error_handler'),
    ]

    operations = [
        migrations.AlterField(
            model_name='cogerror',
            name='task_run',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='errors', to='django_cog.TaskRun'),
        ),
    ]
