"""모델·정책 파라미터를 재현 가능하게 점검하는 분석 함수."""

from __future__ import annotations

import json
import math
import random
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

import pandas as pd
from lightgbm import LGBMRegressor

from score.axis_b_baseline import (
    CATEGORICAL_FEATURE_COLUMNS,
    LGBM_LEARNING_RATE,
    LGBM_MIN_CHILD_SAMPLES,
    LGBM_N_ESTIMATORS,
    LGBM_NUM_LEAVES,
    LGBM_RANDOM_STATE,
    _prepare_valid_rows,
)
from score.axis_b_physics import (
    DEFAULT_DESIGN_SPEED_KN,
    POWER_COEFF_A,
    POWER_COEFF_B,
    SEA_MARGIN_FACTOR,
    SFOC_G_PER_KWH,
)
from score.peer_grouping import build_peer_groups
from score.rate_mapping import RATE_GRADES, grade_for_score
from score.score_assembly import raw_to_score


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TAC_PATH = PROJECT_ROOT / "data_new" / "processed" / "tac_vessels_normalized.jsonl"
PS_TO_KW = 0.73549875
HP_TO_KW = 0.745699872


@dataclass(frozen=True)
class RegressionMetrics:
    sample_size: int
    mae: float
    rmse: float
    r2: float
    mape_percent: float


@dataclass(frozen=True)
class PowerLawFit:
    coefficient_a: float
    exponent_b: float
    log_r2: float


def _finite_float(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def load_tac_power_records(path: Path = DEFAULT_TAC_PATH) -> Tuple[List[dict], Counter]:
    """TAC에서 선박별 양수 GT·기관출력 한 쌍을 읽고 중복·이상치를 제외한다."""
    unique: Dict[str, dict] = {}
    excluded: Counter = Counter()
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            vessel_no = str(row.get("vesselNoTac") or "").strip()
            tonnage = _finite_float(row.get("tonnageGtTac"))
            power = _finite_float(row.get("enginePowerTac"))
            if not vessel_no:
                excluded["missing_vessel_id"] += 1
            elif vessel_no in unique:
                excluded["duplicate_vessel"] += 1
            elif tonnage is None or power is None:
                excluded["missing_or_non_numeric"] += 1
            elif not (0 < tonnage <= 10_000 and 0 < power <= 50_000):
                excluded["non_positive_or_implausible"] += 1
            else:
                unique[vessel_no] = {
                    "vesselId": vessel_no,
                    "tonnageGt": tonnage,
                    "enginePower": power,
                }

    records = list(unique.values())
    if len(records) < 20:
        return records, excluded

    preliminary = fit_power_law(records)
    residuals = sorted(
        math.log(row["enginePower"])
        - math.log(preliminary.coefficient_a * row["tonnageGt"] ** preliminary.exponent_b)
        for row in records
    )
    q1 = residuals[len(residuals) // 4]
    q3 = residuals[(len(residuals) * 3) // 4]
    lower, upper = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
    kept = []
    for row in records:
        residual = math.log(row["enginePower"]) - math.log(
            preliminary.coefficient_a * row["tonnageGt"] ** preliminary.exponent_b
        )
        if lower <= residual <= upper:
            kept.append(row)
        else:
            excluded["log_residual_iqr_outlier"] += 1
    return kept, excluded


def fit_power_law(records: Sequence[dict], power_scale: float = 1.0) -> PowerLawFit:
    """log(P)=log(a)+b*log(GT)를 최소제곱으로 적합한다."""
    if len(records) < 2:
        raise ValueError("회귀에는 두 척 이상이 필요합니다.")
    x = pd.Series([math.log(row["tonnageGt"]) for row in records], dtype=float)
    y = pd.Series([math.log(row["enginePower"] * power_scale) for row in records], dtype=float)
    x_mean, y_mean = x.mean(), y.mean()
    denominator = float(((x - x_mean) ** 2).sum())
    if denominator == 0:
        raise ValueError("톤수 분산이 없어 회귀할 수 없습니다.")
    b = float(((x - x_mean) * (y - y_mean)).sum() / denominator)
    intercept = float(y_mean - b * x_mean)
    predicted = intercept + b * x
    total = float(((y - y_mean) ** 2).sum())
    residual = float(((y - predicted) ** 2).sum())
    return PowerLawFit(math.exp(intercept), b, 1.0 - residual / total if total else 0.0)


def regression_metrics(actual: Sequence[float], predicted: Sequence[float]) -> RegressionMetrics:
    if not actual or len(actual) != len(predicted):
        raise ValueError("실제값과 예측값 길이가 같고 비어 있지 않아야 합니다.")
    errors = [p - a for a, p in zip(actual, predicted)]
    mean_actual = sum(actual) / len(actual)
    ss_res = sum(error * error for error in errors)
    ss_tot = sum((value - mean_actual) ** 2 for value in actual)
    return RegressionMetrics(
        sample_size=len(actual),
        mae=sum(abs(error) for error in errors) / len(errors),
        rmse=math.sqrt(ss_res / len(errors)),
        r2=1.0 - ss_res / ss_tot if ss_tot else 0.0,
        mape_percent=sum(abs(error / value) for value, error in zip(actual, errors) if value) / len(errors) * 100,
    )


def evaluate_power_law(records: Sequence[dict], a: float, b: float, power_scale: float = 1.0) -> RegressionMetrics:
    actual = [row["enginePower"] * power_scale for row in records]
    predicted = [a * row["tonnageGt"] ** b for row in records]
    return regression_metrics(actual, predicted)


def cross_validate_power_law(records: Sequence[dict], folds: int = 5, seed: int = 42) -> RegressionMetrics:
    """선박 단위 결정론적 K-fold의 out-of-fold 예측 지표를 낸다."""
    indices = list(range(len(records)))
    random.Random(seed).shuffle(indices)
    actual, predicted = [], []
    for fold in range(folds):
        valid_indices = set(indices[fold::folds])
        train = [row for index, row in enumerate(records) if index not in valid_indices]
        valid = [row for index, row in enumerate(records) if index in valid_indices]
        fit = fit_power_law(train)
        actual.extend(row["enginePower"] for row in valid)
        predicted.extend(fit.coefficient_a * row["tonnageGt"] ** fit.exponent_b for row in valid)
    return regression_metrics(actual, predicted)


def split_rows_by_vessel(rows: Sequence[dict], validation_fraction: float = 0.2, seed: int = 42):
    """같은 선박이 양쪽에 섞이지 않도록 이벤트를 train/validation으로 나눈다."""
    if not 0 < validation_fraction < 1:
        raise ValueError("validation_fraction은 0과 1 사이여야 합니다.")
    vessel_ids = sorted({row.get("vesselId") for row in rows if row.get("vesselId")})
    random.Random(seed).shuffle(vessel_ids)
    valid_count = max(1, round(len(vessel_ids) * validation_fraction))
    valid_ids = set(vessel_ids[:valid_count])
    train = [row for row in rows if row.get("vesselId") not in valid_ids]
    valid = [row for row in rows if row.get("vesselId") in valid_ids]
    return train, valid


def _feature_frame(rows: Sequence[dict], include_current: bool = True) -> pd.DataFrame:
    numeric = ["tonnageGt", "seaSurfaceTempC", "windSpeedMs", "durationHours"]
    if include_current:
        numeric.insert(3, "currentSpeedMs")
    frame = pd.DataFrame(rows)
    for column in numeric + CATEGORICAL_FEATURE_COLUMNS:
        if column not in frame:
            frame[column] = None
    frame = frame[numeric + CATEGORICAL_FEATURE_COLUMNS].copy()
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    for column in CATEGORICAL_FEATURE_COLUMNS:
        frame[column] = frame[column].astype("category")
    return frame


def validate_lightgbm_baselines(rows: Sequence[dict], seed: int = 42) -> dict:
    """선박 holdout에서 단순 기준선과 작은 LightGBM 후보군을 비교한다."""
    entries, _ = _prepare_valid_rows(list(rows))
    valid_rows = [row for row, _ in entries]
    targets = {id(row): target for row, target in entries}
    train_rows, holdout_rows = split_rows_by_vessel(valid_rows, seed=seed)
    y_train = [targets[id(row)] for row in train_rows]
    y_valid = [targets[id(row)] for row in holdout_rows]
    median = float(pd.Series(y_train).median())
    mean = sum(y_train) / len(y_train)
    results = {
        "split": {
            "train_rows": len(train_rows),
            "validation_rows": len(holdout_rows),
            "train_vessels": len({row["vesselId"] for row in train_rows}),
            "validation_vessels": len({row["vesselId"] for row in holdout_rows}),
        },
        "mean_baseline": asdict(regression_metrics(y_valid, [mean] * len(y_valid))),
        "median_baseline": asdict(regression_metrics(y_valid, [median] * len(y_valid))),
        "candidates": {},
    }
    candidates = {
        "current": (LGBM_N_ESTIMATORS, LGBM_LEARNING_RATE, LGBM_NUM_LEAVES, LGBM_MIN_CHILD_SAMPLES),
        "regularized": (100, 0.05, 7, 20),
        "larger": (100, 0.05, 15, 20),
    }
    prediction_sets = {}
    for include_current in (True, False):
        for name, (trees, rate, leaves, minimum) in candidates.items():
            key = f"{name}_{'with' if include_current else 'without'}_current"
            model = LGBMRegressor(
                n_estimators=trees,
                learning_rate=rate,
                num_leaves=leaves,
                min_child_samples=minimum,
                random_state=seed,
                verbosity=-1,
                n_jobs=1,
            )
            all_x = _feature_frame(train_rows + holdout_rows, include_current)
            train_x = all_x.iloc[: len(train_rows)].copy()
            valid_x = all_x.iloc[len(train_rows) :].copy()
            model.fit(train_x, y_train, categorical_feature=CATEGORICAL_FEATURE_COLUMNS)
            predictions = list(model.predict(valid_x))
            prediction_sets[key] = predictions
            results["candidates"][key] = asdict(regression_metrics(y_valid, predictions))
    with_current = pd.Series(prediction_sets["current_with_current"]).rank()
    without_current = pd.Series(prediction_sets["current_without_current"]).rank()
    results["current_feature_rank_spearman"] = float(with_current.corr(without_current))
    return results


def physics_sensitivity(rows: Sequence[dict], fitted_power: Tuple[float, float] | None = None) -> dict:
    """SFOC·설계속도·출력회귀 변화의 연료 proxy 방향과 규모를 비교한다."""
    entries, _ = _prepare_valid_rows(list(rows))
    sample = [row for row, _ in entries]
    scenarios = {
        "current": (POWER_COEFF_A, POWER_COEFF_B, SFOC_G_PER_KWH, DEFAULT_DESIGN_SPEED_KN),
        "sfoc_170": (POWER_COEFF_A, POWER_COEFF_B, 170.0, DEFAULT_DESIGN_SPEED_KN),
        "sfoc_210": (POWER_COEFF_A, POWER_COEFF_B, 210.0, DEFAULT_DESIGN_SPEED_KN),
        "design_speed_8": (POWER_COEFF_A, POWER_COEFF_B, SFOC_G_PER_KWH, 8.0),
        "design_speed_12": (POWER_COEFF_A, POWER_COEFF_B, SFOC_G_PER_KWH, 12.0),
    }
    if fitted_power:
        scenarios["tac_fitted_power_raw_unit"] = (
            fitted_power[0], fitted_power[1], SFOC_G_PER_KWH, DEFAULT_DESIGN_SPEED_KN
        )
    values = {}
    for name, (a, b, sfoc, design_speed) in scenarios.items():
        values[name] = [
            a * row["tonnageGt"] ** b
            * SEA_MARGIN_FACTOR * (row["averageSpeedKnots"] / design_speed) ** 3
            * sfoc * row["durationHours"] / 1000.0
            for row in sample
        ]
    current = values["current"]
    current_rank = pd.Series(current).rank()
    return {
        name: {
            "median_change_percent": float(
                pd.Series([(value / base - 1) * 100 for value, base in zip(series, current) if base > 0]).median()
            ),
            "rank_spearman": (
                float(current_rank.corr(pd.Series(series).rank())) if len(current) > 1 else 1.0
            ),
        }
        for name, series in values.items()
    }


def peer_parameter_sensitivity(
    vessels: Sequence[dict],
    events: Sequence[dict],
    axis_a_results: Dict[str, object],
    axis_b_results: Dict[str, object],
    *,
    band_widths: Iterable[float] = (5.0, 10.0, 20.0),
    grid_sizes: Iterable[float] = (0.5, 1.0, 2.0),
    minimum_samples: Iterable[int] = (5, 10, 20),
) -> dict:
    """유사군 조합별 상태·그룹 크기·A축 순위 안정성을 계산한다."""
    outputs = {}
    baseline_scores = None
    for band_width in band_widths:
        for grid_size in grid_sizes:
            groups, vessel_to_key = build_peer_groups(list(vessels), list(events), band_width, grid_size)
            sizes = sorted(group.sample_size for group in groups.values())
            for minimum in minimum_samples:
                statuses = Counter()
                scores = {}
                for vessel in vessels:
                    vessel_id = vessel.get("vesselId")
                    axis = axis_a_results.get(vessel_id)
                    if axis is None:
                        statuses["matchingFailed"] += 1
                        continue
                    group = groups[vessel_to_key[vessel_id]]
                    peer_raws = [
                        axis_a_results[peer].axis_a_pressure_raw
                        for peer in group.vessel_ids if peer in axis_a_results
                    ]
                    if len(peer_raws) < minimum:
                        statuses["insufficientSample"] += 1
                        continue
                    scores[vessel_id] = raw_to_score(axis.axis_a_pressure_raw, peer_raws)
                    b_peers = [
                        peer for peer in group.vessel_ids
                        if peer in axis_b_results and axis_b_results[peer].used_row_count > 0
                    ]
                    if vessel_id in b_peers and len(b_peers) >= minimum:
                        statuses["success"] += 1
                    else:
                        statuses["partial"] += 1
                key = f"band{band_width:g}_grid{grid_size:g}_min{minimum}"
                if key == "band10_grid1_min10":
                    baseline_scores = scores
                outputs[key] = {
                    "status": dict(statuses),
                    "groups": len(sizes),
                    "group_size_median": float(pd.Series(sizes).median()),
                    "group_size_p90": float(pd.Series(sizes).quantile(0.9)),
                    "eligible_at_boundary": sum(1 for size in sizes if minimum <= size < minimum * 1.5),
                    "scores": scores,
                }
    if baseline_scores is None:
        return outputs
    baseline_series = pd.Series(baseline_scores)
    for value in outputs.values():
        scores = pd.Series(value.pop("scores"))
        common = baseline_series.index.intersection(scores.index)
        value["axis_a_rank_spearman"] = (
            float(baseline_series.loc[common].rank().corr(scores.loc[common].rank())) if len(common) > 1 else None
        )
    return outputs


def axis_a_weight_sensitivity(groups: Dict[tuple, object], axis_a_results: Dict[str, object], minimum: int = 10) -> dict:
    """고정 유사군에서 A축 결합 가중치 후보의 순위 안정성을 비교한다."""
    candidates = {
        "50_50_interaction10": (0.5, 0.5, 0.1),
        "60_40_interaction10": (0.6, 0.4, 0.1),
        "40_60_interaction10": (0.4, 0.6, 0.1),
        "50_50_no_interaction": (0.5, 0.5, 0.0),
    }
    score_sets = {}
    for name, (revisit_weight, congestion_weight, interaction_weight) in candidates.items():
        scores = {}
        for group in groups.values():
            members = [vessel for vessel in group.vessel_ids if vessel in axis_a_results]
            if len(members) < minimum:
                continue
            raw = {
                vessel: revisit_weight * axis_a_results[vessel].revisit_zscore
                + congestion_weight * axis_a_results[vessel].crowding_zscore
                + interaction_weight * axis_a_results[vessel].interaction_zscore
                for vessel in members
            }
            peer_raws = list(raw.values())
            scores.update({vessel: raw_to_score(value, peer_raws) for vessel, value in raw.items()})
        score_sets[name] = pd.Series(scores)
    baseline = score_sets["50_50_interaction10"]
    return {
        name: {
            "scored_vessels": len(scores),
            "rank_spearman": float(baseline.rank().corr(scores.rank())),
            "median_absolute_score_change": float((scores - baseline).abs().median()),
        }
        for name, scores in score_sets.items()
    }


def bootstrap_peer_stability(
    groups: Dict[tuple, object],
    axis_a_results: Dict[str, object],
    minimum: int = 10,
    repeats: int = 30,
    seed: int = 42,
) -> dict:
    """유사군 내 재표본화로 A축 백분위 점수의 안정성을 요약한다."""
    generator = random.Random(seed)
    original, bootstrapped = {}, {}
    for group in groups.values():
        members = [vessel for vessel in group.vessel_ids if vessel in axis_a_results]
        if len(members) < minimum:
            continue
        raw_values = [axis_a_results[vessel].axis_a_pressure_raw for vessel in members]
        for vessel in members:
            raw = axis_a_results[vessel].axis_a_pressure_raw
            original[vessel] = raw_to_score(raw, raw_values)
            estimates = []
            for _ in range(repeats):
                sample = [raw_values[generator.randrange(len(raw_values))] for _ in raw_values]
                estimates.append(raw_to_score(raw, sample))
            bootstrapped[vessel] = sum(estimates) / len(estimates)
    original_series = pd.Series(original)
    bootstrap_series = pd.Series(bootstrapped)
    return {
        "vessels": len(original),
        "repeats": repeats,
        "rank_spearman": float(original_series.rank().corr(bootstrap_series.rank())),
        "median_absolute_score_change": float((original_series - bootstrap_series).abs().median()),
    }


def score_weight_sensitivity(axis_pairs: Dict[str, Tuple[float, float]]) -> dict:
    """A/B 가중치 후보별 순위와 금리등급 이동을 비교한다."""
    candidates = {"50_50": (0.5, 0.5), "65_35": (0.65, 0.35), "70_30": (0.7, 0.3)}
    score_sets = {
        name: pd.Series({vessel: round(a_weight * pair[0] + b_weight * pair[1], 1) for vessel, pair in axis_pairs.items()})
        for name, (a_weight, b_weight) in candidates.items()
    }
    baseline = score_sets["65_35"]
    baseline_grades = baseline.map(lambda score: grade_for_score(score).grade)
    return {
        name: {
            "rank_spearman": float(baseline.rank().corr(scores.rank())),
            "grade_moves": int((scores.map(lambda score: grade_for_score(score).grade) != baseline_grades).sum()),
        }
        for name, scores in score_sets.items()
    }


def audit_rate_table(scores: Sequence[float]) -> dict:
    """구간·할인 단조성과 경계 처리, 점수별 등급 수를 검사한다."""
    thresholds = [grade.min_score for grade in RATE_GRADES]
    discounts = [grade.discount_bp for grade in RATE_GRADES]
    boundaries = sorted({value for threshold in thresholds for value in (threshold, threshold - 0.1) if value >= 0})
    return {
        "thresholds_descending": thresholds == sorted(thresholds, reverse=True),
        "discounts_descending": discounts == sorted(discounts, reverse=True),
        "boundary_grades": {str(value): grade_for_score(value).grade for value in boundaries},
        "counts": dict(Counter(grade_for_score(score).grade for score in scores)),
    }
