# Generated by Django 2.2.23 on 2021-09-14 19:00

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('django_cog', '0008_task_critical'),
    ]

    operations = [
        migrations.AddField(
            model_name='taskrun',
            name='success',
            field=models.NullBooleanField(),
        ),
    ]
