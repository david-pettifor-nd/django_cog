from django.contrib import admin
from django.shortcuts import HttpResponseRedirect
from . import launch_pipeline
from nested_inline.admin import NestedStackedInline, NestedModelAdmin
from .models import (
    Cog,
    CogErrorHandler,
    Pipeline,
    Stage,
    Task,
    PipelineRun,
    StageRun,
    TaskRun,
    CeleryQueue,
    CogError
)

# Register your models here.
@admin.register(CeleryQueue)
class CeleryQueueAdmin(admin.ModelAdmin):
    list_display = ["queue_name"]
    search_fields = ["queue_name"]

@admin.register(Cog)
class CogAdmin(admin.ModelAdmin):
    list_display = ["name"]
    search_fields = ["name"]

@admin.register(CogError)
class CogErrorAdmin(admin.ModelAdmin):
    list_display = ["get_task_name", "error_type", "timestamp"]

    def get_task_name(self, obj):
        return obj.task_run.task.name

@admin.register(CogErrorHandler)
class CogErrorHandlerAdmin(admin.ModelAdmin):
    list_display = ["name"]
    search_fields = ["name"]

class TasksInline(NestedStackedInline):
    model = Task
    extra = 0
class StagesInLine(NestedStackedInline):
    model = Stage
    inlines = [TasksInline,]
    extra = 0

@admin.register(Pipeline)
class PipelineAdmin(NestedModelAdmin):
    list_display = ["name", "schedule", "enabled"]
    search_fields = ["name"]
    inlines = [StagesInLine,]
    change_form_template = 'change_form.html'

    def response_change(self, request, obj):
        """
        Override to support the "Launch Now" button.
        """
        if "_launchbutton" in request.POST:
            launch_pipeline.apply_async(
                queue='celery',
                kwargs = {
                    'pipeline_id': obj.id, 
                    'user_initiated': True
                })
            self.message_user(request, "Pipeline launch has been initiated.")
            return HttpResponseRedirect(".")
        return super().response_change(request, obj)


@admin.register(Stage)
class StageAdmin(admin.ModelAdmin):
    list_display = ["name", "pipeline"]
    search_fields = ["name"]
    inlines = [TasksInline,]


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ["task_name", "cog", "stage", "pipeline", "queue", "weight"]
    search_fields = ["cog", "queue"]

    def pipeline(self, obj):
        return obj.stage.pipeline
    
    def task_name(self, obj):
        if obj.name:
            return obj.name
        return obj.cog


class StageRunInLine(admin.TabularInline):
    model = StageRun
    extra = 0
    fk_name = 'pipeline_run'
    fieldsets = (
        (
            None, {
                'fields': ('stage', 'started_on', 'completed_on', 'runtime')
            }
        ),(
            'None', {'fields': ()}
        )
    )
    readonly_fields = ('stage', 'started_on', 'completed_on', 'runtime')
    # this is merely for record keeping, and so we shouldn't
    # be adding any through the admin
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

class TaskRunInLine(admin.TabularInline):
    model = TaskRun
    extra = 0
    fk_name = 'stage_run'
    fieldsets = (
        (
            None, {
                'fields': ('task', 'started_on', 'completed_on', 'runtime')
            }
        ),(
            'None', {'fields': ()}
        )
    )
    readonly_fields = ('task', 'started_on', 'completed_on', 'runtime')
    # this is merely for record keeping, and so we shouldn't
    # be adding any through the admin
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(PipelineRun)
class PipelineRunAdmin(admin.ModelAdmin):
    list_display = ["pipeline", "status", "started_on", "completed_on", "runtime"]
    search_fields = ["pipeline", "started_on"]
    inlines = [StageRunInLine,]
    change_form_template = 'cancel_run.html'

    def response_change(self, request, obj):
        """
        Override to support the "Cancel Run" button.
        """
        if "_cancelbutton" in request.POST:
            obj.status = 'Canceled'
            obj.save()
            self.message_user(request, "Pipeline run will halt after its currently running tasks complete.")
            return HttpResponseRedirect(".")
        return super().response_change(request, obj)

@admin.register(StageRun)
class StageRunAdmin(admin.ModelAdmin):
    list_display = ["stage", "pipeline", "status", "started_on", "completed_on", "runtime"]
    search_fields = ["stage", "pipeline", "started_on"]
    inlines = [TaskRunInLine,]

    def pipeline(self, obj):
        return obj.pipeline_run.pipeline


@admin.register(TaskRun)
class TaskRunAdmin(admin.ModelAdmin):
    list_display = ["task", "stage", "pipeline", "status", "started_on", "completed_on", "runtime"]
    search_fields = ["task", "stage", "pipeline", "started_on"]

    def pipeline(self, obj):
        return obj.stage_run.pipeline_run.pipeline
    
    def stage(self, obj):
        return obj.stage_run.stage
