import { useState } from 'react'
import { api } from '../api.js'
import { SpinnerIcon } from './Icons.jsx'

export default function ResearchForm({ onCreated }) {
  const [objective, setObjective] = useState('')
  const [maxPages, setMaxPages] = useState(20)
  const [crawlDepth, setCrawlDepth] = useState(2)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (objective.trim().length < 10) {
      setError('Please enter at least 10 characters.')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const task = await api.createTask(objective.trim(), maxPages, crawlDepth)
      onCreated(task)
      setObjective('')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="card">
      <h2 className="text-xl font-bold text-white mb-4">New Research Task</h2>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-slate-300 mb-1.5">
            Research Objective
          </label>
          <textarea
            className="input h-28 resize-none"
            placeholder='e.g. "Find the top 10 gaming laptops under ₹80,000 in India, compare specs and recommend the best."'
            value={objective}
            onChange={e => setObjective(e.target.value)}
            disabled={loading}
            required
          />
          <p className="text-xs text-slate-500 mt-1">
            Describe your research goal in natural language. More detail = better results.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">
              Max Pages <span className="text-slate-500 font-normal">(3–100)</span>
            </label>
            <input type="number" className="input" min={3} max={100}
              value={maxPages} onChange={e => setMaxPages(Number(e.target.value))} disabled={loading} />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">
              Crawl Depth <span className="text-slate-500 font-normal">(1–5)</span>
            </label>
            <input type="number" className="input" min={1} max={5}
              value={crawlDepth} onChange={e => setCrawlDepth(Number(e.target.value))} disabled={loading} />
          </div>
        </div>

        {error && (
          <p className="text-red-400 text-sm bg-red-900/30 border border-red-900 rounded-lg px-4 py-2">
            {error}
          </p>
        )}

        <button type="submit" className="btn-primary w-full flex items-center justify-center gap-2" disabled={loading}>
          {loading ? <><SpinnerIcon /> Starting…</> : 'Start Research'}
        </button>
      </form>
    </div>
  )
}
