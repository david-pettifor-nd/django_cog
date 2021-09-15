# Generated by Django 2.2.23 on 2021-09-15 13:27

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('django_cog', '0012_cogerror'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='error_handler',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tasks', to='django_cog.CogErrorHandler'),
        ),
    ]