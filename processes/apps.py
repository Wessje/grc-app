"""
Registers the processes module ("processes" app) with Django.

A process here is either a business process or a solution you run, such as
payroll or email. Risks will be connected to one of these.
"""

from django.apps import AppConfig


class ProcessesConfig(AppConfig):
    name = "processes"
    verbose_name = "Processes"
