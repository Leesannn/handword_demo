"""손목 상대 손 모양과 어깨 기준 손 위치를 구분하는 실험용 변환."""
VARIANTS=('original','local_hands_keep_pose','local_hands_keep_pose_add_wrists')


def transform(features,variant):
    import numpy as np
    x=np.asarray(features,dtype=np.float32)
    if variant not in VARIANTS:raise ValueError('지원하지 않는 특징 구성입니다.')
    if x.ndim not in (2,3) or x.shape[-2:]!=(30,177) or not np.isfinite(x).all():
        raise ValueError('입력은 유한한 값의 (30,177) 또는 (N,30,177)이어야 합니다.')
    mask_values=x[...,118:]
    if not np.isin(mask_values,[0,1]).all():raise ValueError('검출 마스크는 0 또는 1이어야 합니다.')
    shape=x.shape[:-1]
    xy=x[...,:118].reshape(*shape,59,2)
    mask=mask_values.astype(bool)
    if np.any(xy[~mask]!=0):raise ValueError('입력의 미검출 XY는 0이어야 합니다.')
    if variant=='original':return x.copy()
    local=xy.copy();local_mask=mask.copy()
    for offset in (0,21):
        good=mask[...,offset:offset+21]&mask[...,offset:offset+1]
        relative=xy[...,offset:offset+21,:]-xy[...,offset:offset+1,:]
        local[...,offset:offset+21,:]=np.where(good[...,None],relative,0)
        local_mask[...,offset:offset+21]=good
    blocks=[local.reshape(*shape,118),local_mask.astype(np.float32)]
    if variant=='local_hands_keep_pose_add_wrists':
        wrist_mask=mask[...,[0,21]]
        wrists=np.where(wrist_mask[...,None],xy[...,[0,21],:],0)
        blocks.extend([wrists.reshape(*shape,4),wrist_mask.astype(np.float32)])
    return np.concatenate(blocks,axis=-1).astype(np.float32)
