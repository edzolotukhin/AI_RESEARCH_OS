"""The explicit production catalogue; test methods register in tests only."""
from application.methods.registry import MethodRegistry
from application.methods.desk.binding import DeskBinding


def production_methods():
    return MethodRegistry((DeskBinding(),))
