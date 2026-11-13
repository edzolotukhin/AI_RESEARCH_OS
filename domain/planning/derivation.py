"""Explicit, immutable specifications for bounded Analysis derivations."""
from dataclasses import dataclass
from enum import StrEnum
import re


class InformationNeedKind(StrEnum):
    ACQUIRED = "ACQUIRED"
    DERIVED = "DERIVED"
    OUTPUT = "OUTPUT"


class DerivationOperation(StrEnum):
    YEAR_OVER_YEAR_ABSOLUTE_CHANGE = "YEAR_OVER_YEAR_ABSOLUTE_CHANGE"
    YEAR_OVER_YEAR_PERCENT_CHANGE = "YEAR_OVER_YEAR_PERCENT_CHANGE"
    CUMULATIVE_ABSOLUTE_CHANGE = "CUMULATIVE_ABSOLUTE_CHANGE"
    CUMULATIVE_PERCENT_CHANGE = "CUMULATIVE_PERCENT_CHANGE"
    TREND_CHARACTERIZATION = "TREND_CHARACTERIZATION"
    CROSS_SOURCE_COMPARISON = "CROSS_SOURCE_COMPARISON"
    LIMITATION_SYNTHESIS = "LIMITATION_SYNTHESIS"

    @property
    def deterministic(self):
        return self.value.endswith("_CHANGE")


@dataclass(frozen=True)
class DerivationContract:
    operation_type: DerivationOperation
    metric: str
    input_unit: str
    geography: str
    required_periods: tuple[str, ...] = ()
    decimal_places: int = 6
    max_inputs: int = 100
    max_provider_attempts: int = 1
    method: str = ""
    version: str = "derivation-v1"

    def __post_init__(self):
        object.__setattr__(self,"operation_type",DerivationOperation(self.operation_type))
        object.__setattr__(self,"required_periods",tuple(self.required_periods))
        if self.version != "derivation-v1":
            raise ValueError("Unsupported derivation contract version")
        if any(not isinstance(v,str) or not v.strip() for v in (self.metric,self.input_unit,self.geography)):
            raise ValueError("Derivation requires explicit metric, input_unit and geography")
        if any(len(v)>200 for v in (self.metric,self.input_unit,self.geography)):
            raise ValueError("Derivation labels exceed bounds")
        if not 0<=self.decimal_places<=12 or not 1<=self.max_inputs<=100 or not 1<=self.max_provider_attempts<=2:
            raise ValueError("Invalid derivation bounds")
        periods=self.required_periods
        if len(periods)>self.max_inputs:
            raise ValueError("Required periods exceed input bound")
        if len(set(periods))!=len(periods) or any(not re.fullmatch(r"(?:19|20)\d{2}",p) for p in periods) or tuple(sorted(periods))!=periods:
            raise ValueError("Derivation periods must be unique ordered explicit years")
        if self.operation_type.deterministic and len(periods)<2:
            raise ValueError("Calculation requires at least two explicit periods")
        if self.operation_type==DerivationOperation.TREND_CHARACTERIZATION and len(periods)<2:
            raise ValueError("Trend synthesis requires explicit comparison periods")
        if self.operation_type.value.startswith("YEAR_OVER_YEAR") and any(int(b)-int(a)!=1 for a,b in zip(periods,periods[1:])):
            raise ValueError("YoY requires consecutive years")
        if not self.operation_type.deterministic and (not self.method.strip() or len(self.method)>500):
            raise ValueError("Semantic synthesis requires a bounded explicit method")

    def to_dict(self):
        return {"version":self.version,"operation_type":self.operation_type.value,"metric":self.metric,
                "input_unit":self.input_unit,"geography":self.geography,"required_periods":list(self.required_periods),
                "decimal_places":self.decimal_places,"max_inputs":self.max_inputs,
                "max_provider_attempts":self.max_provider_attempts,"method":self.method}

    @classmethod
    def from_dict(cls,payload):
        if not isinstance(payload,dict) or "version" not in payload:
            raise ValueError("Explicit derivation version required")
        return cls(**payload)


def validate_dependency_graph(design):
    needs={n.id:n for n in design.information_needs}
    if len(needs)!=len(design.information_needs):
        raise ValueError("Duplicate Information Need ID")
    visiting,done=set(),set()
    ordered=[]
    def visit(need):
        if need.id in visiting:
            raise ValueError("Information Need dependency cycle")
        if need.id in done:
            return
        visiting.add(need.id)
        for ref in need.depends_on_information_need_ids:
            if ref==need.id or ref not in needs:
                raise ValueError("Unknown or self-referencing Information Need dependency")
            if need.kind==InformationNeedKind.DERIVED and needs[ref].kind==InformationNeedKind.OUTPUT:
                raise ValueError("Derived input cannot be an OUTPUT requirement")
            visit(needs[ref])
        visiting.remove(need.id)
        done.add(need.id)
        ordered.append(need)
    for need in design.information_needs:
        if need.research_question_id not in {q.id for q in design.research_questions}:
            raise ValueError("Information Need references a foreign Research Question")
        visit(need)
    return tuple(ordered)
