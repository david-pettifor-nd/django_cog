import pytz
import time
import json
from django.test import TestCase
from django.conf import settings
from .models import Pipeline, Stage, Task, Cog, PipelineRun, StageRun, TaskRun, CogError, CeleryQueue
from . import cog, cog_error_handler
from .apps import create_cog_records
from django_celery_beat.models import CrontabSchedule
from django.utils import timezone
from . import launch_pipeline, launch_stage, launch_task
from celery import current_app


class CogTestCase(TestCase):
    def setUp(self):
        @cog
        def test_function():
            return True
        
        @cog
        def failing_function():
            raise Exception("Test error")
        
        @cog_error_handler
        def test_error_handler(error, task_run=None):
            if task_run:
                CogError.objects.create(
                    task_run=task_run,
                    error_type=type(error).__name__,
                    traceback=str(error)
                )
        
        create_cog_records()
        
        # Create default queue
        self.default_queue = CeleryQueue.objects.create(
            queue_name="celery"
        )
        
        # Configure Celery to execute tasks synchronously in tests
        current_app.conf.update(
            task_always_eager=True,
            task_eager_propagates=True,
        )

    def test_cog_registration(self):
        """
        Test the function registration purely by
        checking if the name exists in our global
        "cog" object.
        """
        self.assertEqual((
            'test_function' in cog.all
        ), True)
    
    def test_cog_model_creation(self):
        """
        Test the function registration purely by
        checking if the name exists in our global
        "cog" object.
        """
        self.assertEqual(
            Cog.objects.filter(name='test_function').exists(),
            True
        )

    def test_pipeline_creation(self):
        """
        Test creating a pipeline with stages and tasks
        """
        # Create a default queue
        default_queue = CeleryQueue.objects.create(
            queue_name="celery"
        )
        
        # Create a pipeline
        pipeline = Pipeline.objects.create(
            name="Test Pipeline",
            enabled=True,
            prevent_overlapping_runs=True
        )
        
        # Create stages
        stage1 = Stage.objects.create(
            name="Stage 1",
            pipeline=pipeline
        )
        
        stage2 = Stage.objects.create(
            name="Stage 2",
            pipeline=pipeline
        )
        stage2.launch_after_stage.add(stage1)
        
        # Create tasks
        task1 = Task.objects.create(
            cog=Cog.objects.get(name='test_function'),
            stage=stage1,
            enabled=True,
            queue=default_queue
        )
        
        task2 = Task.objects.create(
            cog=Cog.objects.get(name='test_function'),
            stage=stage2,
            enabled=True,
            queue=default_queue
        )
        
        # Verify pipeline structure
        self.assertEqual(pipeline.stages.count(), 2)
        self.assertEqual(stage1.assigned_tasks.count(), 1)
        self.assertEqual(stage2.assigned_tasks.count(), 1)
        self.assertEqual(stage2.launch_after_stage.count(), 1)

    def test_pipeline_execution(self):
        """
        Test executing a pipeline with stages and tasks
        """        
        # Create pipeline structure
        pipeline = Pipeline.objects.create(
            name="Test Pipeline",
            enabled=True
        )
        
        stage = Stage.objects.create(
            name="Test Stage",
            pipeline=pipeline
        )
        
        task = Task.objects.create(
            cog=Cog.objects.get(name='test_function'),
            stage=stage,
            enabled=True,
            queue=self.default_queue
        )
        
        # Launch the pipeline
        launch_pipeline(pipeline_id=pipeline.id)
        
        # Wait for pipeline to complete
        max_wait = 5  # seconds
        start_time = time.time()
        while time.time() - start_time < max_wait:
            pipeline_run = PipelineRun.objects.filter(pipeline=pipeline).first()
            if pipeline_run and pipeline_run.completed_on:
                break
            time.sleep(0.1)
        
        # Verify pipeline execution
        self.assertIsNotNone(pipeline_run, "Pipeline run was not created")
        self.assertEqual(pipeline_run.status, 'Completed')
        self.assertTrue(pipeline_run.success)
        
        # Verify stage run
        stage_run = pipeline_run.stage_runs.first()
        self.assertIsNotNone(stage_run, "Stage run was not created")
        self.assertEqual(stage_run.status, 'Completed')
        self.assertTrue(stage_run.success)
        
        # Verify task run
        task_run = stage_run.task_runs.first()
        self.assertIsNotNone(task_run, "Task run was not created")
        self.assertEqual(task_run.status, 'Completed')
        self.assertTrue(task_run.success)
        
        # Verify all relationships
        self.assertEqual(pipeline_run.stage_runs.count(), 1)
        self.assertEqual(stage_run.task_runs.count(), 1)
        self.assertEqual(task_run.stage_run, stage_run)
        self.assertEqual(stage_run.pipeline_run, pipeline_run)

    def test_task_error_handling(self):
        """
        Test error handling in task execution
        """        
        # Create pipeline structure
        pipeline = Pipeline.objects.create(
            name="Error Test Pipeline",
            enabled=True
        )
        
        stage = Stage.objects.create(
            name="Error Test Stage",
            pipeline=pipeline
        )
        
        # Create task with failing function
        task = Task.objects.create(
            cog=Cog.objects.get(name='failing_function'),
            stage=stage,
            enabled=True,
            queue=self.default_queue
        )
        
        # launch the pipeline
        launch_pipeline(pipeline_id=pipeline.id)

        # wait for the pipeline to complete
        max_wait = 5  # seconds
        start_time = time.time()
        while time.time() - start_time < max_wait:
            pipeline_run = PipelineRun.objects.filter(pipeline=pipeline).first()
            if pipeline_run and pipeline_run.completed_on:
                break
            time.sleep(0.1)
        

        # Verify error was recorded
        self.assertEqual(CogError.objects.count(), 1)
        error = CogError.objects.first()
        self.assertEqual(error.error_type, 'Exception')

    def test_pipeline_overlap_prevention(self):
        """
        Test prevention of overlapping pipeline runs
        """
        pipeline = Pipeline.objects.create(
            name="Overlap Test Pipeline",
            enabled=True,
            prevent_overlapping_runs=True
        )

        # add a stage
        stage = Stage.objects.create(
            name="Overlap Test Stage",
            pipeline=pipeline
        )

        # add a failing task
        task = Task.objects.create(
            name="Failing Task",
            cog=Cog.objects.get(name='failing_function'),
            stage=stage,
            enabled=True,
            queue=self.default_queue
        )
        
        # launch the pipeline to get one successful run
        launch_pipeline(pipeline_id=pipeline.id)

        # wait for the pipeline to complete
        max_wait = 5  # seconds
        start_time = time.time()
        while time.time() - start_time < max_wait:
            pipeline_run = PipelineRun.objects.filter(pipeline=pipeline).first()
            if pipeline_run and pipeline_run.completed_on:
                break
            time.sleep(0.1)

        print("Pipeline Runs: ", PipelineRun.objects.filter(pipeline=pipeline).count())
       

        # launch the pipeline again
        launch_pipeline(pipeline_id=pipeline.id)
        
        # Verify only one running pipeline exists
        self.assertEqual(
            PipelineRun.objects.filter(
                pipeline=pipeline
            ).count(),
            1
        )

    def test_stage_dependencies(self):
        """
        Test stage dependencies and execution order
        """
        pipeline = Pipeline.objects.create(
            name="Dependency Test Pipeline",
            enabled=True
        )
        
        # Create stages with dependencies
        stage1 = Stage.objects.create(
            name="First Stage",
            pipeline=pipeline
        )
        
        stage2 = Stage.objects.create(
            name="Second Stage",
            pipeline=pipeline
        )
        stage2.launch_after_stage.add(stage1)
        
        # Create pipeline run
        pipeline_run = PipelineRun.objects.create(
            pipeline=pipeline
        )
        
        # Create stage runs
        stage_run1 = StageRun.objects.create(
            stage=stage1,
            pipeline_run=pipeline_run,
            status='Completed',
            completed_on=timezone.now()
        )
        
        stage_run2 = StageRun.objects.create(
            stage=stage2,
            pipeline_run=pipeline_run
        )
        
        # Verify stage dependency
        self.assertEqual(stage2.launch_after_stage.first(), stage1)
        self.assertTrue(stage_run1.completed_on is not None)
