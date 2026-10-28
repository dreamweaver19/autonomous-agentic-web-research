import { Routes, Route, Link, useLocation } from 'react-router-dom'
import Dashboard from './pages/Dashboard.jsx'
import TaskDetail from './pages/TaskDetail.jsx'

function NavLink({ to, children }) {
  const { pathname } = useLocation()
  const active = pathname === to
  return (
    <Link
      to={to}
      className={`text-sm transition-colors ${active ? 'text-white font-medium' : 'text-slate-400 hover:text-slate-200'}`}
    >
      {children}
    </Link>
  )
}

export default function App() {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-slate-800 bg-slate-900/90 backdrop-blur sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-3 flex items-center gap-6">
          <Link to="/" className="flex items-center gap-2 text-brand-500 font-bold text-lg tracking-tight">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <span>Research Agent</span>
          </Link>
          <nav className="flex gap-5 ml-auto">
            <NavLink to="/">Dashboard</NavLink>
          </nav>
        </div>
      </header>

      <main className="flex-1 max-w-7xl mx-auto w-full px-4 sm:px-6 py-8">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/task/:taskId" element={<TaskDetail />} />
        </Routes>
      </main>

      <footer className="text-center text-xs text-slate-600 py-4 border-t border-slate-800">
        Autonomous Agentic Web Research System
      </footer>
    </div>
  )
}
