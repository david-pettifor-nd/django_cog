from django.contrib import admin
from nested_inline.admin import NestedStackedInline, NestedModelAdmin
from .models import (
    Cog,
    Pipeline,
    Stage,
    Task,
    PipelineRun,
    StageRun,
    TaskRun
)

# Register your models here.

@admin.register(Cog)
class CogAdmin(admin.ModelAdmin):
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


@admin.register(Stage)
class StageAdmin(admin.ModelAdmin):
    list_display = ["name", "pipeline"]
    search_fields = ["name"]
    inlines = [TasksInline,]


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ["task_name", "cog", "stage", "pipeline"]
    search_fields = ["cog"]

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
    list_display = ["pipeline", "started_on", "completed_on", "runtime"]
    search_fields = ["pipeline", "started_on"]
    inlines = [StageRunInLine,]

@admin.register(StageRun)
class StageRunAdmin(admin.ModelAdmin):
    list_display = ["stage", "pipeline", "started_on", "completed_on", "runtime"]
    search_fields = ["stage", "pipeline", "started_on"]
    inlines = [TaskRunInLine,]

    def pipeline(self, obj):
        return obj.pipeline_run.pipeline


@admin.register(TaskRun)
class TaskRunAdmin(admin.ModelAdmin):
    list_display = ["task", "stage", "pipeline", "started_on", "completed_on", "runtime"]
    search_fields = ["task", "stage", "pipeline", "started_on"]

    def pipeline(self, obj):
        return obj.stage_run.pipeline_run.pipeline
    
    def stage(self, obj):
        return obj.stage_run.stage
