"""
Comprehensive Constraint Validation System
Includes: historical bounds, cascade validation, cross-parameter checks
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from enum import Enum
import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class ConstraintSeverity(Enum):
    """Severity level of constraint violation"""
    CRITICAL = "critical"  # Hard limit - reject immediately
    WARNING = "warning"    # Soft limit - warn but allow
    INFO = "info"          # FYI only


class ConstraintSource(Enum):
    """Source of constraint"""
    HISTORICAL = "historical_data"      # From 189k records
    GOST = "gost_standard"             # GOST R 52368-2005
    TECHNICAL = "technical_doc"         # Equipment specs
    LITERATURE = "literature"           # Kapustin V.M. textbook
    CORRELATION = "correlation_analysis" # From our analysis
    PHYSICS = "physical_limit"          # Fundamental physics


@dataclass
class Constraint:
    """Single constraint definition"""
    param_name: str
    param_description: str

    # Hard limits (critical)
    hard_min: Optional[float] = None
    hard_max: Optional[float] = None

    # Soft limits (recommended)
    soft_min: Optional[float] = None
    soft_max: Optional[float] = None

    # Metadata
    unit: str = ""
    severity: ConstraintSeverity = ConstraintSeverity.CRITICAL
    source: ConstraintSource = ConstraintSource.HISTORICAL
    reason: str = ""
    reference: Optional[str] = None

    # Historical statistics (if available)
    hist_min: Optional[float] = None
    hist_max: Optional[float] = None
    hist_mean: Optional[float] = None
    hist_std: Optional[float] = None
    hist_p5: Optional[float] = None
    hist_p95: Optional[float] = None


@dataclass
class ValidationResult:
    """Result of constraint validation"""
    valid: bool
    violations: List[str]
    warnings: List[str]
    checked_params: Dict[str, float]

    def __bool__(self):
        return self.valid


class ConstraintRegistry:
    """Registry of all constraints with historical data"""

    def __init__(self):
        self.constraints: Dict[str, Constraint] = {}
        self._load_default_constraints()

    def _load_default_constraints(self):
        """Load constraints based on 189k records + domain knowledge"""

        # ===== АВТ ПАРАМЕТРЫ =====

        # AVT_F7 - Расход верхнего орошения
        self.add_constraint(Constraint(
            param_name="AVT_F7",
            param_description="Расход верхнего орошения",
            hard_min=5.0, hard_max=55.0,
            soft_min=25.0, soft_max=35.0,
            unit="т/ч",
            source=ConstraintSource.HISTORICAL,
            reason="Hard: исторический диапазон с 10% буфером. Soft: p25-p75 из данных",
            hist_min=10.2, hist_max=49.8, hist_mean=30.1, hist_std=5.2
        ))

        # AVT_F9 - Расход циркуляции (ДРЕЙФУЕТ!)
        self.add_constraint(Constraint(
            param_name="AVT_F9",
            param_description="Расход циркуляции АВТ (⚠️ дрейфует +2.87/мес)",
            hard_min=40.0, hard_max=160.0,
            soft_min=95.0, soft_max=105.0,
            unit="т/ч",
            source=ConstraintSource.TECHNICAL,
            reason="Hard: минимум для циркуляции + мощность насоса. Soft: текущая уставка ± σ",
            reference="Технологический регламент + анализ дрейфа (R²=0.44)",
            hist_min=50.1, hist_max=149.3, hist_mean=100.2, hist_std=12.5
        ))

        # AVT_F41 - Расход бокового погона (высокая корреляция!)
        self.add_constraint(Constraint(
            param_name="AVT_F41",
            param_description="Расход бокового погона (ρ=0.65 с H24_F25)",
            hard_min=18.0, hard_max=85.0,
            soft_min=45.0, soft_max=55.0,
            unit="т/ч",
            source=ConstraintSource.HISTORICAL,
            reason="Определяет сырье для гидроочистки, сильная корреляция с выходом",
            hist_min=20.3, hist_max=79.7, hist_mean=50.2, hist_std=8.1
        ))

        # AVT_F46 - Расход нижнего орошения
        self.add_constraint(Constraint(
            param_name="AVT_F46",
            param_description="Расход нижнего орошения",
            hard_min=10.0, hard_max=65.0,
            soft_min=30.0, soft_max=40.0,
            unit="т/ч",
            source=ConstraintSource.HISTORICAL,
            reason="Контроль температурного профиля низа колонны",
            hist_min=15.2, hist_max=59.8
        ))

        # AVT_F65 - Расход на гидроочистку
        self.add_constraint(Constraint(
            param_name="AVT_F65",
            param_description="Расход на гидроочистку",
            hard_min=25.0, hard_max=105.0,
            soft_min=55.0, soft_max=65.0,
            unit="т/ч",
            source=ConstraintSource.HISTORICAL,
            reason="Материальный баланс АВТ → Гидроочистка",
            hist_min=30.1, hist_max=98.7
        ))

        # AVT_T42 - Температура бокового погона (КЛЮЧЕВОЙ!)
        self.add_constraint(Constraint(
            param_name="AVT_T42",
            param_description="Температура бокового погона (ρ=0.704 с H24_P8!)",
            hard_min=195.0, hard_max=285.0,
            soft_min=235.0, soft_max=250.0,
            unit="°C",
            source=ConstraintSource.HISTORICAL,
            reason="Hard: физика + буфер. Soft: p5-p95 (90% данных). Сильно влияет на H24_P8!",
            reference="Корреляционный анализ: ρ=0.704 с H24_P8",
            hist_min=200.1, hist_max=279.8, hist_mean=242.5, hist_std=8.3,
            hist_p5=235.2, hist_p95=249.8
        ))

        # AVT_T48 - Температура стриппинга
        self.add_constraint(Constraint(
            param_name="AVT_T48",
            param_description="Температура стриппинга",
            hard_min=175.0, hard_max=255.0,
            soft_min=210.0, soft_max=220.0,
            unit="°C",
            source=ConstraintSource.HISTORICAL,
            hist_min=180.2, hist_max=248.9
        ))

        # AVT_T55 - Температура мазута (КРИТИЧНО!)
        self.add_constraint(Constraint(
            param_name="AVT_T55",
            param_description="Температура мазута (риск коксования > 370°C!)",
            hard_min=275.0, hard_max=370.0,
            soft_min=315.0, soft_max=350.0,
            unit="°C",
            severity=ConstraintSeverity.CRITICAL,
            source=ConstraintSource.LITERATURE,
            reason="КРИТИЧНО: > 370°C интенсивное коксообразование, опасность для печи",
            reference="Капустин В.М. Технология переработки нефти. Часть 1. 2012, стр. 156",
            hist_min=280.5, hist_max=358.2
        ))

        # AVT_P51 - Давление в колонне
        self.add_constraint(Constraint(
            param_name="AVT_P51",
            param_description="Давление в колонне АВТ",
            hard_min=1.3, hard_max=3.5,
            soft_min=1.8, soft_max=2.2,
            unit="кгс/см²",
            source=ConstraintSource.TECHNICAL,
            reason="Hard: проектное давление колонны. Soft: оптимальная зона",
            reference="Проектная документация К-1",
            hist_min=1.5, hist_max=2.8
        ))

        # ===== ГИДРООЧИСТКА 24-2000 =====

        # H24_F15 - Расход продукта (ρ=0.98 с target!)
        self.add_constraint(Constraint(
            param_name="H24_F15",
            param_description="Расход продукта гидроочистки (ρ=0.98 с H24_F25!)",
            hard_min=15.0, hard_max=75.0,
            soft_min=40.0, soft_max=50.0,
            unit="т/ч",
            source=ConstraintSource.HISTORICAL,
            reason="САМАЯ СИЛЬНАЯ корреляция с выходом! Прямая связь с качеством",
            reference="Корреляционный анализ: ρ=0.98",
            hist_min=20.1, hist_max=68.9, hist_mean=45.2, hist_std=7.8
        ))

        # H24_F26 - Расход циркуляции Г/О (ρ=0.87!)
        self.add_constraint(Constraint(
            param_name="H24_F26",
            param_description="Расход циркуляции Г/О (ρ=0.87 с H24_F25)",
            hard_min=30.0, hard_max=130.0,
            soft_min=75.0, soft_max=90.0,
            unit="т/ч",
            severity=ConstraintSeverity.CRITICAL,
            source=ConstraintSource.TECHNICAL,
            reason="КРИТИЧНО: < 30 т/ч → перегрев реактора, риск дезактивации катализатора",
            reference="Технологический регламент Р-202",
            hist_min=40.2, hist_max=118.7, hist_mean=82.1, hist_std=15.3
        ))

        # H24_T5 - Температура верха (ρ=0.76)
        self.add_constraint(Constraint(
            param_name="H24_T5",
            param_description="Температура верха Г/О (ρ=0.76 с H24_F25)",
            hard_min=145.0, hard_max=225.0,
            soft_min=180.0, soft_max=190.0,
            unit="°C",
            source=ConstraintSource.HISTORICAL,
            reason="Влияет на фракционный состав продукта",
            hist_min=150.3, hist_max=218.9, hist_mean=185.2, hist_std=9.1
        ))

        # H24_T6 - Температура газойля (ρ=0.74)
        self.add_constraint(Constraint(
            param_name="H24_T6",
            param_description="Температура газойля (ρ=0.74 с H24_F25)",
            hard_min=195.0, hard_max=290.0,
            soft_min=235.0, soft_max=245.0,
            unit="°C",
            severity=ConstraintSeverity.CRITICAL,
            source=ConstraintSource.LITERATURE,
            reason="> 290°C: термическое разложение сырья",
            reference="Капустин В.М., стр. 203",
            hist_min=200.5, hist_max=278.3, hist_mean=240.1, hist_std=10.2
        ))

        # H24_T11 - Температура продукта (ρ=0.71)
        self.add_constraint(Constraint(
            param_name="H24_T11",
            param_description="Температура продукта (ρ=0.71 с H24_F25)",
            hard_min=175.0, hard_max=265.0,
            soft_min=215.0, soft_max=230.0,
            unit="°C",
            source=ConstraintSource.HISTORICAL,
            reason="Оптимальная зона для качества и выхода",
            hist_min=180.2, hist_max=258.7, hist_mean=220.5, hist_std=11.8
        ))

        # H24_P8 - Давление реактора (ЦЕНТРАЛЬНЫЙ ИНДИКАТОР!)
        self.add_constraint(Constraint(
            param_name="H24_P8",
            param_description="Давление реактора Г/О (центральный индикатор!)",
            hard_min=20.0, hard_max=50.0,
            soft_min=32.0, soft_max=38.0,
            unit="кгс/см²",
            severity=ConstraintSeverity.CRITICAL,
            source=ConstraintSource.TECHNICAL,
            reason=(
                "Hard: < 20 → недостаточная активность катализатора, > 50 → проектный предел. "
                "ЦЕНТРАЛЬНЫЙ индикатор: коррелирует с 4 топ параметрами (AVT_T42 ρ=0.704)"
            ),
            reference="Проектная документация Р-202 + корреляционный анализ",
            hist_min=25.1, hist_max=44.8, hist_mean=34.5, hist_std=3.2,
            hist_p5=31.2, hist_p95=37.8
        ))

        # H24_P13 - Давление сепаратора
        self.add_constraint(Constraint(
            param_name="H24_P13",
            param_description="Давление сепаратора",
            hard_min=18.0, hard_max=42.0,
            soft_min=28.0, soft_max=32.0,
            unit="кгс/см²",
            source=ConstraintSource.TECHNICAL,
            reason="Проектное давление С-201",
            hist_min=20.5, hist_max=38.9
        ))

        logger.info(f"Loaded {len(self.constraints)} constraints from historical data + domain knowledge")

    def add_constraint(self, constraint: Constraint):
        """Add or update constraint"""
        self.constraints[constraint.param_name] = constraint

    def get_constraint(self, param_name: str) -> Optional[Constraint]:
        """Get constraint for parameter"""
        return self.constraints.get(param_name)

    def get_all_constrained_params(self) -> List[str]:
        """Get list of all parameters with constraints"""
        return list(self.constraints.keys())


class CascadeValidator:
    """
    Cascade validation: check input → predict intermediate → check output
    """

    def __init__(self, constraint_registry: ConstraintRegistry, model=None, scaler=None):
        self.registry = constraint_registry
        self.model = model
        self.scaler = scaler

        # Cross-parameter constraints
        self.cross_constraints = self._load_cross_constraints()

    def _load_cross_constraints(self) -> List[Dict]:
        """Define cross-parameter constraints based on correlations"""
        return [
            {
                'name': 'AVT_T42_H24_P8_coupling',
                'condition': lambda params: params.get('AVT_T42', 0) > 250,
                'requires': lambda params: params.get('H24_P8', 0) > 33,
                'reason': 'При высокой температуре сырья (AVT_T42 > 250°C) требуется поддерживать давление H24_P8 > 33 кгс/см²',
                'source': 'Корреляционный анализ: ρ=0.704, sensitivity=0.15'
            },
            {
                'name': 'reactor_operation_safety',
                'condition': lambda params: params.get('H24_T11', 0) > 200,
                'requires': lambda params: params.get('H24_F26', 0) > 50,
                'reason': 'При работающем реакторе (T11 > 200°C) необходима достаточная циркуляция (F26 > 50 т/ч)',
                'source': 'Технологический регламент'
            },
            {
                'name': 'avt_material_balance',
                'condition': lambda params: params.get('AVT_F41', 0) > 0 and params.get('AVT_F9', 0) > 0,
                'requires': lambda params: (params.get('AVT_F41', 0) / max(params.get('AVT_F9', 1), 0.1)) < 0.8,
                'reason': 'Расход бокового погона не должен превышать 80% от циркуляции',
                'source': 'Материальный баланс АВТ'
            },
            {
                'name': 'coking_prevention',
                'condition': lambda params: params.get('AVT_T55', 0) > 350,
                'requires': lambda params: params.get('AVT_F9', 0) > 90,
                'reason': 'При высокой температуре (> 350°C) нужна усиленная циркуляция для предотвращения коксования',
                'source': 'Капустин В.М.'
            }
        ]

    def validate_input_params(self, params: Dict[str, float]) -> ValidationResult:
        """Step 1: Validate input parameters against constraints"""
        violations = []
        warnings = []

        for param_name, value in params.items():
            constraint = self.registry.get_constraint(param_name)

            if not constraint:
                warnings.append(f"No constraint defined for {param_name}")
                continue

            # Check hard limits
            if constraint.hard_min is not None and value < constraint.hard_min:
                violations.append(
                    f"❌ {constraint.param_description} = {value:.2f} {constraint.unit} "
                    f"< hard_min {constraint.hard_min:.2f} | "
                    f"Причина: {constraint.reason} | Источник: {constraint.source.value}"
                )

            if constraint.hard_max is not None and value > constraint.hard_max:
                violations.append(
                    f"❌ {constraint.param_description} = {value:.2f} {constraint.unit} "
                    f"> hard_max {constraint.hard_max:.2f} | "
                    f"Причина: {constraint.reason} | Источник: {constraint.source.value}"
                )

            # Check soft limits
            if constraint.soft_min is not None and value < constraint.soft_min:
                warnings.append(
                    f"⚠️ {constraint.param_description} = {value:.2f} {constraint.unit} "
                    f"< soft_min {constraint.soft_min:.2f} (рекомендуемый минимум)"
                )

            if constraint.soft_max is not None and value > constraint.soft_max:
                warnings.append(
                    f"⚠️ {constraint.param_description} = {value:.2f} {constraint.unit} "
                    f"> soft_max {constraint.soft_max:.2f} (рекомендуемый максимум)"
                )

        return ValidationResult(
            valid=(len(violations) == 0),
            violations=violations,
            warnings=warnings,
            checked_params=params
        )

    def validate_cross_constraints(self, params: Dict[str, float]) -> ValidationResult:
        """Step 2: Validate cross-parameter constraints"""
        violations = []
        warnings = []

        for cc in self.cross_constraints:
            try:
                if cc['condition'](params):
                    if not cc['requires'](params):
                        violations.append(
                            f"❌ Cross-constraint '{cc['name']}': {cc['reason']} | "
                            f"Источник: {cc['source']}"
                        )
            except Exception as e:
                warnings.append(f"⚠️ Could not check {cc['name']}: {e}")

        return ValidationResult(
            valid=(len(violations) == 0),
            violations=violations,
            warnings=warnings,
            checked_params=params
        )

    def predict_and_validate_output(self, input_params: Dict[str, float]) -> ValidationResult:
        """Step 3: Predict output and validate"""
        violations = []
        warnings = []

        if self.model is None:
            warnings.append("⚠️ Model not loaded, skipping output validation")
            return ValidationResult(valid=True, violations=[], warnings=warnings, checked_params={})

        # TODO: Implement full prediction with all 45 features
        # For now, simplified check
        warnings.append("⚠️ Output validation: simplified version (full model requires 45 features)")

        return ValidationResult(valid=True, violations=violations, warnings=warnings, checked_params={})

    def validate_full_cascade(self, input_params: Dict[str, float]) -> ValidationResult:
        """Full cascade: input → cross → output"""
        all_violations = []
        all_warnings = []

        # Step 1: Input validation
        input_result = self.validate_input_params(input_params)
        all_violations.extend(input_result.violations)
        all_warnings.extend(input_result.warnings)

        if not input_result.valid:
            return ValidationResult(
                valid=False,
                violations=all_violations,
                warnings=all_warnings,
                checked_params=input_params
            )

        # Step 2: Cross-parameter validation
        cross_result = self.validate_cross_constraints(input_params)
        all_violations.extend(cross_result.violations)
        all_warnings.extend(cross_result.warnings)

        if not cross_result.valid:
            return ValidationResult(
                valid=False,
                violations=all_violations,
                warnings=all_warnings,
                checked_params=input_params
            )

        # Step 3: Output prediction validation
        output_result = self.predict_and_validate_output(input_params)
        all_violations.extend(output_result.violations)
        all_warnings.extend(output_result.warnings)

        return ValidationResult(
            valid=(len(all_violations) == 0),
            violations=all_violations,
            warnings=all_warnings,
            checked_params=input_params
        )


# ===== USAGE EXAMPLE =====

def demo():
    """Demo of cascade validation"""

    # Initialize
    registry = ConstraintRegistry()
    validator = CascadeValidator(registry)

    print("="*80)
    print("CONSTRAINT VALIDATION DEMO")
    print("="*80)

    # Scenario 1: Valid changes
    print("\n[Scenario 1] Небольшие изменения в пределах нормы:")
    params1 = {
        'AVT_T42': 245.0,  # В рекомендуемом диапазоне [235, 250]
        'H24_P8': 35.0,    # В рекомендуемом диапазоне [32, 38]
        'H24_F26': 85.0    # В рекомендуемом диапазоне [75, 90]
    }

    result1 = validator.validate_full_cascade(params1)
    print(f"Valid: {result1.valid}")
    print(f"Violations: {len(result1.violations)}")
    print(f"Warnings: {len(result1.warnings)}")
    for w in result1.warnings:
        print(f"  {w}")

    # Scenario 2: Hard limit violation
    print("\n[Scenario 2] Превышение жесткого ограничения:")
    params2 = {
        'AVT_T55': 375.0,  # > 370°C - КОКСОВАНИЕ!
        'H24_P8': 35.0
    }

    result2 = validator.validate_full_cascade(params2)
    print(f"Valid: {result2.valid}")
    for v in result2.violations:
        print(f"  {v}")

    # Scenario 3: Cross-constraint violation
    print("\n[Scenario 3] Нарушение cross-constraint:")
    params3 = {
        'AVT_T42': 255.0,  # Высокая температура
        'H24_P8': 30.0     # Но давление недостаточное!
    }

    result3 = validator.validate_full_cascade(params3)
    print(f"Valid: {result3.valid}")
    for v in result3.violations:
        print(f"  {v}")

    print("\n" + "="*80)
    print(f"Total constraints loaded: {len(registry.constraints)}")
    print(f"Constrained parameters: {', '.join(registry.get_all_constrained_params()[:5])}...")


if __name__ == '__main__':
    demo()
