from django.apps import AppConfig


def create_cog_records():
    """
    This function loops through any known
    registered cogs and creates Cog objects
    for them.
    """
    try:
        from .models import Cog
        from . import cog
        active_cogs = []
        for cog_name, function in cog.all.items():
            Cog.objects.get_or_create(
                name=cog_name
            )
            active_cogs.append(cog_name)

        # remove any that are no longer registered\
        Cog.objects.all().exclude(name__in=active_cogs).delete()
    except Exception as e:
        print(e)
        print("Failed to clean up cogs.  Maybe try running migrations?")


class DjangoCogConfig(AppConfig):
    name = 'django_cog'

    def ready(self):
        create_cog_records()
