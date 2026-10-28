import { SpinnerIcon, CheckIcon, XIcon } from './Icons.jsx'

const CFG = {
  pending:   { label: 'Pending',   cls: 'bg-slate-700 text-slate-300',   Icon: null },
  planning:  { label: 'Planning',  cls: 'bg-yellow-900/70 text-yellow-300', Icon: SpinnerIcon },
  running:   { label: 'Running',   cls: 'bg-blue-900/70 text-blue-300',   Icon: SpinnerIcon },
  completed: { label: 'Completed', cls: 'bg-green-900/70 text-green-300', Icon: CheckIcon },
  failed:    { label: 'Failed',    cls: 'bg-red-900/70 text-red-300',     Icon: XIcon },
  cancelled: { label: 'Cancelled', cls: 'bg-slate-800 text-slate-500',    Icon: XIcon },
}

export default function StatusBadge({ status }) {
  const { label, cls, Icon } = CFG[status] ?? CFG.pending
  return (
    <span className={`badge gap-1 ${cls}`}>
      {Icon && <Icon className="w-3 h-3" />}
      {label}
    </span>
  )
}
