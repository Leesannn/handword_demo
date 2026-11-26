"""NumPy kNN baseline: choose k on validation only, then evaluate the held-out test."""
import argparse
import collections
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time


def predict(train_x, train_y, query_x, k, class_count):
    import numpy as np
    if not 1 <= k <= len(train_x):
        raise ValueError('k가 학습 표본 수 범위를 벗어납니다.')
    predictions, fractions = [], []
    for query in query_x:
        distances = np.sqrt(np.sum((train_x - query) ** 2, axis=1))
        nearest = np.argsort(distances, kind='stable')[:k]
        votes = np.bincount(train_y[nearest], minlength=class_count)
        tied = np.flatnonzero(votes == votes.max())
        # Deterministic tie policy, fixed before looking at validation/test results.
        chosen = min(tied, key=lambda label: (float(distances[nearest][train_y[nearest] == label].sum()), int(label)))
        predictions.append(int(chosen))
        fractions.append(float(votes[chosen] / k))
    return np.asarray(predictions, dtype=np.int64), np.asarray(fractions)


def metrics(truth, predictions, classes):
    import numpy as np
    matrix = np.zeros((len(classes), len(classes)), dtype=int)
    for actual, guess in zip(truth, predictions):
        matrix[int(actual), int(guess)] += 1
    per_class = []
    for i, label in enumerate(classes):
        tp = int(matrix[i, i])
        support = int(matrix[i].sum())
        predicted = int(matrix[:, i].sum())
        precision = tp / predicted if predicted else 0.0
        recall = tp / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class.append({'class_id': label, 'support': support, 'precision': precision, 'recall': recall, 'f1': f1})
    return {'samples': len(truth), 'correct': int((truth == predictions).sum()),
            'accuracy': float((truth == predictions).mean()),
            'macro_f1': sum(r['f1'] for r in per_class) / len(classes),
            'per_class': per_class, 'confusion_matrix_rows_actual_columns_predicted': matrix.tolist()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=Path(__file__).resolve().parent.parent / '04_데이터' / 'ksl_data' / 'aihub_baseline_v1')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent.parent / '04_데이터' / 'ksl_data' / 'knn_baseline_v1')
    args = parser.parse_args()
    import numpy as np
    if args.output.exists() and any(args.output.iterdir()):
        raise FileExistsError('이름이 같은 학습 결과가 있습니다. 기존 결과 확인 또는 다른 --output 경로를 사용하세요.')
    started = time.perf_counter()
    spec_path = args.dataset / 'preprocessing.json'
    spec = json.loads(spec_path.read_text(encoding='utf-8'))
    shapes = {'aihub-2d-upper50-nearest30-v1': (30,150),
              'mediapipe-xy59-mask59-nearest30-v1': (30,177)}
    if spec.get('preprocessing_version') not in shapes:
        raise ValueError('지원하는 전처리 버전이 아닙니다.')
    classes = spec['class_names']
    if len(classes) != 8 or len(set(classes)) != 8:
        raise ValueError('8개 임시 클래스 구성을 확인하세요.')
    dataset_path = args.dataset / 'dataset.npz'
    with np.load(dataset_path, allow_pickle=False) as data:
        x = data['X'].astype(np.float64)
        y = data['y'].copy()
        split = data['split'].copy()
        groups = data['subject_group'].copy()
        sequence = data['sequence_id'].copy()
    if x.shape[1:] != shapes[spec['preprocessing_version']] or not np.isfinite(x).all() or not (len(x) == len(y) == len(split) == len(groups) == len(sequence)):
        raise ValueError('입력 배열 크기 또는 수치를 확인하세요.')
    if len(set(sequence.tolist())) != len(sequence) or not np.isin(y, np.arange(len(classes))).all():
        raise ValueError('시퀀스 또는 정답 라벨이 올바르지 않습니다.')
    if set(split.tolist()) != {'train', 'validation', 'test'}:
        raise ValueError('분할 이름을 확인하세요.')
    sets = {s: set(groups[split == s].tolist()) for s in ['train', 'validation', 'test']}
    if sets['train'] & sets['validation'] or sets['train'] & sets['test'] or sets['validation'] & sets['test']:
        raise ValueError('촬영 코드 그룹이 학습/평가에 중복됩니다.')
    for name in sets:
        if set(y[split == name].tolist()) != set(range(len(classes))):
            raise ValueError(f'{name}에 모든 클래스가 있지 않습니다.')
    flat = x.reshape(len(x), -1)
    train = split == 'train'
    validation = split == 'validation'
    test = split == 'test'
    train_x, train_y = flat[train], y[train]
    trials = []
    validation_predictions = {}
    for k in [1, 3, 5]:
        guess, vote = predict(train_x, train_y, flat[validation], k, len(classes))
        score = metrics(y[validation], guess, classes)
        trials.append({'k': k, 'correct': score['correct'], 'samples': score['samples'],
                       'accuracy': score['accuracy'], 'macro_f1': score['macro_f1']})
        validation_predictions[k] = (guess, vote)
        print(f"검증 k={k}: {score['correct']}/{score['samples']} ({score['accuracy']:.1%})", flush=True)
    # Test data never participates in k selection. Keep the 76 training samples fixed.
    best = min(trials, key=lambda r: (-r['accuracy'], r['k']))
    k = best['k']
    test_guess, test_vote = predict(train_x, train_y, flat[test], k, len(classes))
    validation_guess, validation_vote = validation_predictions[k]
    validation_result = metrics(y[validation], validation_guess, classes)
    test_result = metrics(y[test], test_guess, classes)
    args.output.mkdir(parents=True, exist_ok=True)
    model_path = args.output / 'knn_model.npz'
    np.savez_compressed(model_path, train_X=train_x.astype(np.float32), train_y=train_y,
                        class_names=np.asarray(classes), k=np.asarray(k, dtype=np.int64))
    with np.load(model_path, allow_pickle=False) as saved:
        # Model storage uses float32, matching the original prepared feature precision.
        reload_guess, _ = predict(saved['train_X'].astype(np.float64), saved['train_y'], flat[test], int(saved['k']), len(classes))
        if not np.array_equal(reload_guess, test_guess):
            raise ValueError('저장 후 모델 예측이 원래 예측과 다릅니다.')
    predictions = []
    for name, selection, guess, votes in [('validation', validation, validation_guess, validation_vote),
                                           ('test', test, test_guess, test_vote)]:
        for index, prediction, fraction in zip(np.flatnonzero(selection), guess, votes):
            predictions.append({'split': name, 'sequence_id': str(sequence[index]), 'subject_group': str(groups[index]),
                                'actual': classes[int(y[index])], 'predicted': classes[int(prediction)],
                                'correct': bool(y[index] == prediction), 'neighbor_vote_fraction': float(fraction)})
    with (args.output / 'predictions.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(predictions[0])); writer.writeheader(); writer.writerows(predictions)
    with (args.output / 'test_confusion_matrix.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream); writer.writerow(['actual / predicted', *classes])
        for label, row in zip(classes, test_result['confusion_matrix_rows_actual_columns_predicted']):
            writer.writerow([label, *row])
    report = {
        'created_at_utc': datetime.now(timezone.utc).isoformat(), 'algorithm': 'NumPy kNN, Euclidean, uniform votes',
        'tie_rule': 'Most votes; then least total neighbor distance for tied class; then class index',
        'k_selection_rule': 'Highest validation accuracy among 1/3/5, then smaller k. Test excluded from selection.',
        'selected_k': k, 'train_samples': int(train.sum()), 'split_counts': dict(collections.Counter(split.tolist())),
        'groups': {name: sorted(value) for name, value in sets.items()}, 'class_names': classes,
        'preprocessing_version': spec['preprocessing_version'],
        'dataset_sha256': hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        'validation_trials': trials, 'validation': validation_result, 'test': test_result,
        'numpy_version': np.__version__, 'script_elapsed_seconds': time.perf_counter() - started,
        'limitations': ['8 provisional classes, not the final five-word model',
                       ('AIHub supplied 2D landmarks; no live camera evaluation' if spec['preprocessing_version']=='aihub-2d-upper50-nearest30-v1' else 'MediaPipe landmarks extracted from AIHub videos; no live camera or app evaluation'),
                       'No other/unknown class or unknown rejection evaluated',
                       'Source-code groups separated; real-person identities remain independently unverified',
                       'Small fixed exploratory split; no cross-validation or deployment latency evaluation',
                       'Neighbor vote fraction is not calibrated correctness probability',
                       'Do not repeatedly tune against this already observed test split'],
    }
    (args.output / 'evaluation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (args.output / 'preprocessing.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding='utf-8')
    print('\n=== kNN 기준선 결과 ===')
    print(f'선택 k: {k} / 학습: {int(train.sum())}개')
    print(f"검증: {validation_result['correct']}/{validation_result['samples']} ({validation_result['accuracy']:.1%})")
    print(f"테스트: {test_result['correct']}/{test_result['samples']} ({test_result['accuracy']:.1%})")
    print(f"테스트 Macro F1: {test_result['macro_f1']:.3f}")
    print(f'결과 폴더: {args.output.resolve()}')
    print('8개 임시 클래스의 작은 보류 데이터 평가입니다. 앱 실사용 정확도나 unknown 성능이 아닙니다.')


if __name__ == '__main__':
    main()
