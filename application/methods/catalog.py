"""The explicit production catalogue; test methods register in tests only."""
from application.methods.registry import MethodRegistry
from application.methods.desk.binding import DeskBinding
from application.methods.quantitative.binding import QuantitativeBinding
from application.methods.qualitative.binding import QualitativeBinding


def production_methods():
    return MethodRegistry((DeskBinding(), QuantitativeBinding(), QualitativeBinding()))
