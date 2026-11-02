"""Repair only observed spelling aliases, never coordinates or model decisions."""
from copy import deepcopy

ALIASES = {'bbox_0_0_1000': 'bbox_0_1000', 'target_point_0_000': 'target_point_0_1000'}


def normalize_observation(raw):
    value = deepcopy(raw)
    repairs = []
    if not isinstance(value, dict):
        return value, repairs
    regions = [('plate', value.get('plate'))]
    if isinstance(value.get('anomalies'), list):
        regions.extend((f'anomalies.{i}', item) for i, item in enumerate(value['anomalies']))
    for path, region in regions:
        if not isinstance(region, dict):
            continue
        for alias, canonical in ALIASES.items():
            if alias not in region:
                continue
            if canonical in region and region[alias] is None:
                # Several recorded replies included a correct point plus an
                # extra misspelled null field. Preserve the canonical value.
                region.pop(alias)
                repairs.append({'path': path, 'from': alias, 'to': canonical, 'action': 'drop_empty_alias'})
                continue
            # Conflicting geometry remains invalid. Do not silently choose one.
            if canonical in region and region[canonical] != region[alias]:
                continue
            region[canonical] = region.pop(alias)
            repairs.append({'path': path, 'from': alias, 'to': canonical})
    return value, repairs
