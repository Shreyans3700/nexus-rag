import { Monitor, Moon, Sun } from 'lucide-react'
import type { Theme } from '../context/ThemeContext'
import { useTheme } from '../context/ThemeContext'

const OPTIONS: { value: Theme; label: string; Icon: typeof Sun }[] = [
  { value: 'light', label: 'Light', Icon: Sun },
  { value: 'system', label: 'System', Icon: Monitor },
  { value: 'dark', label: 'Dark', Icon: Moon },
]

export function ThemeToggle() {
  const { theme, setTheme } = useTheme()

  return (
    <div className="flex gap-0.5 rounded-full border border-border bg-surface p-1">
      {OPTIONS.map(({ value, label, Icon }) => (
        <button
          key={value}
          type="button"
          onClick={() => setTheme(value)}
          title={label}
          aria-label={label}
          className={`flex h-6 w-6 items-center justify-center rounded-full transition-colors ${
            theme === value ? 'bg-accent-soft text-accent' : 'text-ink-muted hover:text-ink'
          }`}
        >
          <Icon size={13} strokeWidth={2} />
        </button>
      ))}
    </div>
  )
}
