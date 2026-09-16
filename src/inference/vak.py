"""Deterministic VAK equations supplied by the organizers on 2026-09-16."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


class VakInputError(ValueError):
    pass


@dataclass(frozen=True)
class VakFormula:
    model: str
    required: tuple[str, ...]
    unit: str
    calculate: Callable[[dict[str, float]], float]


def _ratio(a: float, b: float, label: str) -> float:
    if abs(b) < 1e-9:
        raise VakInputError(f"Zero denominator in {label}")
    return a / b


FORMULAS = (
    VakFormula("AVT6:240-350:D15", ("F65", "F32", "F30", "T66", "T33"), "kg/m³", lambda x: 791.22872 - 5.30294*_ratio(x["F65"], x["F32"]+x["F30"], "F65/(F32+F30)") + .52755*x["T66"] - .15629*x["T33"]),
    VakFormula("AVT6:240-350:T50", ("F7", "F30", "F34", "F45", "F59", "F63"), "°C", lambda x: 283.177 - .01685*x["F7"] + .06248*x["F30"] + .22048*x["F34"] - .25816*x["F45"] - .12159*x["F59"] + .01221*x["F63"]),
    VakFormula("AVT6:240-350:CFPP", ("T33", "P67", "P4", "F65", "F32", "F30"), "°C", lambda x: 31.40363 - .06784*x["T33"] + 17.411*x["P67"] - 8.11544*x["P4"] - .47309*_ratio(x["F65"], x["F32"]+x["F30"], "F65/(F32+F30)")),
    VakFormula("AVT6:240-350:EBP", ("F30", "T33", "F36", "T37", "T40", "T58"), "°C", lambda x: 813.883 + 2.66463*x["F30"] - .20239*x["T33"] - 3.65888*x["F36"] - 14.08235*x["T37"] - 1.32603*x["T40"] + 14.60206*x["T58"]),
    VakFormula("AVT6:350-500:ViscosityK", ("T6", "T13", "T18", "T20", "L43", "T48", "P50", "F53", "P51", "F59", "T61"), "cSt", lambda x: 5.831 + .00976*x["T6"] + .01188*x["T13"] + .00224*x["T18"] + .01905*x["T20"] + .00794*x["L43"] - .02496*x["T48"] - .00008*x["P50"] - .00882*x["F53"] - .00394*x["P51"] - .00255*x["F59"] + .01153*x["T61"]),
    VakFormula("AVT6:350:CFPP", ("T48", "T40", "F31", "F57"), "°C", lambda x: 19.27111 - .10582*x["T48"] + .13836*x["T40"] - .42304*_ratio(x["F31"], x["F57"], "F31/F57")),
    VakFormula("AVT6:350:T50", ("T42", "T48", "F31", "F57", "T66", "T33"), "°C", lambda x: 493.6798 + 1.281193*x["T42"] - .955342*x["T48"] - .018454*x["F31"] + .265904*x["F57"] - .082047*x["T66"] - .545083*x["T33"]),
    VakFormula("AVT6:350:I350", ("L43", "T6", "T18", "F64", "T15", "T11"), "index", lambda x: 39.562 - 1.62865*x["L43"] + .76664*x["T6"] - .22361*x["T18"] + .00031*x["F64"]*(x["T15"]-x["T11"])),
    VakFormula("AVT6:350:D15", ("T42", "T48", "F31", "F57"), "kg/m³", lambda x: 983.092 + .27467*x["T42"] - .49014*x["T48"] - .32983*_ratio(x["F31"], x["F57"], "F31/F57")),
)


def evaluate_vak(values: dict[str, float], selected: list[str] | None = None) -> list[dict]:
    wanted = set(selected or [f.model for f in FORMULAS])
    unknown = wanted - {f.model for f in FORMULAS}
    if unknown:
        raise VakInputError("Unknown VAK models: " + ", ".join(sorted(unknown)))
    result = []
    for formula in FORMULAS:
        if formula.model not in wanted:
            continue
        missing = [tag for tag in formula.required if tag not in values]
        if missing:
            result.append({"model": formula.model, "status": "unavailable", "missing": missing, "unit": formula.unit})
            continue
        try:
            value = float(formula.calculate(values))
            result.append({"model": formula.model, "status": "ok", "value": value, "unit": formula.unit})
        except VakInputError as exc:
            result.append({"model": formula.model, "status": "invalid", "reason": str(exc), "unit": formula.unit})
    return result
