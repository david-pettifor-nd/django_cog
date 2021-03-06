# Generated by Django 2.2.23 on 2021-09-15 19:33

from django.db import migrations, models

def default_prior_entities(apps, schema_editor):
    entity_run_model = apps.get_model("django_cog", "EntityRun")
    for run in entity_run_model.objects.all():
        run.status = 'Completed'
        run.save()

class Migration(migrations.Migration):

    dependencies = [
        ('django_cog', '0016_auto_20210915_1042'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='cogerror',
            options={'ordering': ['-timestamp']},
        ),
        migrations.AddField(
            model_name='entityrun',
            name='status',
            field=models.CharField(choices=[('Queued', 'Queued'), ('Running', 'Running'), ('Failed', 'Failed'), ('Completed', 'Completed'), ('Canceled', 'Canceled')], default='Queued', max_length=10),
        ),
        migrations.RunPython(default_prior_entities)
    ]
