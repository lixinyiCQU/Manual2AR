"""File-based, module-one-only CPU tuning; no credentials."""
import math

DEFAULTS = dict(target_fps=10, capture_max_side=640, jpeg_quality=78,
    request_timeout_seconds=3, recovery_seconds=2.5, recovery_max_frames=20,
    max_corners=100, minimum_points=8, forward_backward_error=1.5,
    minimum_inlier_ratio=0.65, maximum_residual=2.5,
    minimum_appearance_correlation=0.55, maximum_motion_ratio=0.18,
    minimum_scale=0.85, maximum_scale=1.18, png_compression=1)


def validate(settings):
    unknown=set(settings)-set(DEFAULTS)
    if unknown:
        raise ValueError('Unknown cpu_tracking settings: '+', '.join(sorted(unknown)))
    value={**DEFAULTS,**settings}
    limits=dict(target_fps=(1,30),capture_max_side=(160,1280),jpeg_quality=(40,95),
        request_timeout_seconds=(1,10),recovery_seconds=(0.1,5),recovery_max_frames=(1,100),
        max_corners=(8,300),minimum_points=(4,100),forward_backward_error=(0.1,4),
        minimum_inlier_ratio=(0.5,1),maximum_residual=(0.2,5),
        minimum_appearance_correlation=(0.45,0.99),maximum_motion_ratio=(0.01,0.3),
        minimum_scale=(0.6,1),maximum_scale=(1,1.5),png_compression=(0,9))
    integers={'capture_max_side','jpeg_quality','request_timeout_seconds','recovery_max_frames','max_corners','minimum_points','png_compression'}
    for name,(lo,hi) in limits.items():
        n=value[name]
        if isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or not lo<=n<=hi:
            raise ValueError(f'cpu_tracking.{name} must be in [{lo},{hi}]')
        if name in integers and not isinstance(n,int):
            raise ValueError('cpu_tracking.'+name+' must be an integer')
    if value['minimum_points']>value['max_corners']:
        raise ValueError('minimum_points exceeds max_corners')
    return value
