import pytz
import time
from django.test import TestCase
from django.conf import settings
from .models import Pipeline, Stage, Task, Cog, PipelineRun, StageRun, TaskRun
from . import cog
from .apps import create_cog_records
from django_celery_beat.models import CrontabSchedule

class CogTestCase(TestCase):
    def setUp(self):
        @cog
        def test_function():
            return True
        
        create_cog_records()

    def test_cog_registration(self):
        """
        Test the function registration purely by
        checking if the name exists in our global
        "cog" object.
        """
        self.assertEquals((
            'test_function' in cog.all
        ), True)
    
    def test_cog_model_creation(self):
        """
        Test the function registration purely by
        checking if the name exists in our global
        "cog" object.
        """
        self.assertEquals(
            Cog.objects.filter(name='test_function').exists(),
            True
        )
