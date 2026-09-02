"""Command classes for global, project, self, and root-level workflows.

:mod:`rn_forge.agentkit.cli` is the complete Typer command-line surface: it constructs
one of these classes from the Typer context per invocation and calls the matching
method. Shared output, adapter-selection, and failure helpers live on
:class:`~rn_forge.agentkit.commands.base.BaseCommand`.
"""
