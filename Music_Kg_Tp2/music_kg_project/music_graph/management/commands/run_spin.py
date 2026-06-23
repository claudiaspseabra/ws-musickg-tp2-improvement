from django.core.management.base import BaseCommand
from music_graph.spin_rules import execute_all_rules

class Command(BaseCommand):
    help = 'Executes all custom SPIN/SPARQL inference rules against GraphDB'

    def handle(self, *args, **kwargs):
        self.stdout.write("Running inference rules...")
        execute_all_rules()
        self.stdout.write(self.style.SUCCESS('Successfully classified all entities!'))