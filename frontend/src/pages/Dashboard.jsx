import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import ResearchForm from '../components/ResearchForm.jsx'
import StatusBadge from '../components/StatusBadge.jsx'
import ProgressBar from '../components/ProgressBar.jsx'
import { SpinnerIcon } from '../components/Icons.jsx'

const ACTIVE = ['pending', 'planning', 'running']

function TaskCard({ task, onClick }) {
  const isActive = ACTIVE.includes(task.status)
  return (
    <div
      onClick={onClick}
      className="card cursor-pointer hover:border-slate-600 transition-colors space-y-3"
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium text-white line-clamp-2 flex-1">
          {task.objective}
        </p>
        <StatusBadge status={task.status} />
      </div>

      {isActive && (
        <ProgressBar value={task.progress_percent ?? 0} label="Progress" />
      )}

      <div className="flex items-center justify-between text-xs text-slate-500">
        <span>{task.pages_crawled ?? 0} pages crawled</span>
        <span>{new Date(task.created_at).toLocaleString()}</span>
      </div>

      {task.stopping_reason && (
        <p className="text-xs text-slate-500 italic truncate">{task.stopping_reason}</p>
      )}
    </div>
  )
}

export default function Dashboard() {
  const navigate = useNavigate()
  const [tasks, setTasks] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [backendOk, setBackendOk] = useState(null)

  const fetchTasks = useCallback(async () => {
    try {
      const data = await api.listTasks()
      setTasks(data.tasks ?? [])
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  // Check backend health on mount
  useEffect(() => {
    api.getHealth()
      .then(() => setBackendOk(true))
      .catch(() => setBackendOk(false))
  }, [])

  // Initial load
  useEffect(() => { fetchTasks() }, [fetchTasks])

  // Poll active tasks every 4 seconds
  useEffect(() => {
    const hasActive = tasks.some(t => ACTIVE.includes(t.status))
    if (!hasActive) return
    const id = setInterval(fetchTasks, 4000)
    return () => clearInterval(id)
  }, [tasks, fetchTasks])

  const handleCreated = (task) => {
    setTasks(prev => [task, ...prev])
    navigate(`/task/${task.task_id}`)
  }

  return (
    <div className="space-y-8">
      {/* Backend status banner */}
      {backendOk === false && (
        <div className="bg-red-900/40 border border-red-800 rounded-xl px-5 py-4 text-red-300 text-sm">
          ⚠️ Cannot reach the backend at <code>http://localhost:8000</code>. Make sure the Python server is running.
        </div>
      )}

      <div className="grid lg:grid-cols-[1fr_1.6fr] gap-8 items-start">
        <ResearchForm onCreated={handleCreated} />

        {/* Task list */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-bold text-white">Research Tasks</h2>
            <button onClick={fetchTasks} className="btn-secondary text-xs px-3 py-1.5">
              Refresh
            </button>
          </div>

          {loading && (
            <div className="flex items-center gap-2 text-slate-400 text-sm">
              <SpinnerIcon /> Loading tasks…
            </div>
          )}

          {error && (
            <p className="text-red-400 text-sm">{error}</p>
          )}

          {!loading && tasks.length === 0 && (
            <div className="card text-center py-12 text-slate-500">
              No research tasks yet. Create one on the left.
            </div>
          )}

          <div className="space-y-3">
            {tasks.map(task => (
              <TaskCard
                key={task.task_id}
                task={task}
                onClick={() => navigate(`/task/${task.task_id}`)}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
