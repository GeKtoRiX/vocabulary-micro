import type { StageInfo } from '../api/types'

interface Props {
  stages: StageInfo[]
  open: boolean
}

const STATUS_LABELS: Record<StageInfo['status'], string> = {
  loading: 'In progress',
  done: 'Done',
  error: 'Error',
}

function renderIcon(status: StageInfo['status']) {
  if (status === 'loading') {
    return <span className="spinner stage-icon-loading" aria-hidden="true" />
  }

  return (
    <span
      className={status === 'done' ? 'stage-icon stage-icon-done' : 'stage-icon stage-icon-error'}
      aria-hidden="true"
    >
      {status === 'done' ? 'OK' : 'ERR'}
    </span>
  )
}

export function StageProgressPopup({ stages, open }: Props) {
  if (!open || stages.length === 0) {
    return null
  }

  return (
    <div className="stage-popup-overlay" role="presentation">
      <div className="stage-popup" role="status" aria-live="polite" aria-label="Processing stages">
        <div className="stage-popup-title">Processing...</div>
        {stages.map((stage) => (
          <div key={stage.stage} className="stage-item">
            {renderIcon(stage.status)}
            <div className="stage-copy">
              <div className="stage-label">{stage.label}</div>
              <div className="stage-status">{STATUS_LABELS[stage.status]}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
