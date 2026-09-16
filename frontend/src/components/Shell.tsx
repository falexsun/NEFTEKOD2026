import { useEffect, useState } from 'react'
import { Activity, ChevronRight, Clock3, Gauge, History, Menu, ShieldAlert, SlidersHorizontal, X } from 'lucide-react'
import type { Readiness } from '../types'
import { StatusBadge } from './ui'

export type View = 'shift' | 'scenario' | 'loops' | 'journal'

const nav: Array<{ id: View; label: string; icon: typeof Activity }> = [
  { id: 'shift', label: 'Текущая смена', icon: Activity },
  { id: 'scenario', label: 'Сценарии', icon: SlidersHorizontal },
  { id: 'loops', label: 'Контуры', icon: Gauge },
  { id: 'journal', label: 'Журнал решений', icon: History },
]

function Logo() {
  return <div className="logo"><span className="logo-mark">НК</span><span>НЕФТЕКОД<small>КОНТУР КАЧЕСТВА</small></span></div>
}

export function Shell({ view, onNavigate, readiness, children }: { view: View; onNavigate: (view: View) => void; readiness?: Readiness; children: React.ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000)
    return () => window.clearInterval(timer)
  }, [])
  const runtimeState = !readiness ? 'unknown' : readiness.ready ? 'normal' : readiness.quality_model_ready ? 'warning' : 'unavailable'
  const runtimeLabel = !readiness ? 'Нет связи' : readiness.ready ? 'Контур готов' : readiness.quality_model_ready ? 'Накопление истории' : 'Модель недоступна'

  return <div className="app-shell">
    <aside className={`sidebar ${menuOpen ? 'is-open' : ''}`}>
      <button className="mobile-close" onClick={() => setMenuOpen(false)} aria-label="Закрыть меню"><X size={20} /></button>
      <Logo />
      <div className="sidebar-label">РАБОЧАЯ ОБЛАСТЬ</div>
      <nav aria-label="Основная навигация">
        {nav.map(({ id, label, icon: Icon }) => <button key={id} className={view === id ? 'active' : ''} aria-current={view === id ? 'page' : undefined} onClick={() => { onNavigate(id); setMenuOpen(false) }}><Icon size={18} /><span>{label}</span></button>)}
      </nav>
      <div className="chain"><div className="sidebar-label">ТЕХНОЛОГИЧЕСКАЯ ЦЕПОЧКА</div><div className="chain-line"><span className="done">АВТ</span><i /><span className="focus">24—2000</span><i /><span>Блендинг</span></div><p>Рекомендательный контур. Без автоматической передачи в АСУ ТП.</p></div>
      <div className="operator"><div className="avatar">ОП</div><div><strong>Рабочее место</strong><span>Оператор смены</span></div><ChevronRight size={17} /></div>
    </aside>
    {menuOpen && <button className="scrim" onClick={() => setMenuOpen(false)} aria-label="Закрыть меню" />}
    <div className="main-shell">
      <header className="topbar">
        <button className="menu-button" onClick={() => setMenuOpen(true)} aria-label="Открыть меню"><Menu size={20} /></button>
        <div className="breadcrumbs"><span>АВТ → 24—2000</span><ChevronRight size={15} /><b>{nav.find(item => item.id === view)?.label}</b></div>
        <div className="top-actions"><StatusBadge state={runtimeState}>{runtimeLabel}</StatusBadge><span className="timestamp"><Clock3 size={15} />{now.toLocaleString('ru-RU', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>{readiness && !readiness.storage_ready && <span title="Журнал недоступен"><ShieldAlert size={18} className="critical-icon" /></span>}</div>
      </header>
      <main>{children}</main>
    </div>
  </div>
}
