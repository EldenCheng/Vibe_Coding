import { useMemo, type ReactNode } from 'react'
import type { QuestionTransition as TransitionKind } from '../config/configLoader'

interface Props {
  transitionKey: string | number
  effect: TransitionKind
  children: ReactNode
}

const RANDOM_POOL: TransitionKind[] = ['fade', 'slide', 'flip', 'scatter']

// v0.3.1 切题转场容器：以 transitionKey 为 key 重新挂载触发 CSS 动画；random 每次按 key 选一种
// 说明：不依赖系统减少动态效果设置（用户确认：简单过渡即可，配置即所见）
export function QuestionTransition({ transitionKey, effect, children }: Props) {
  const resolved: TransitionKind = useMemo(() => {
    if (effect === 'random') {
      const n = typeof transitionKey === 'number' ? transitionKey : transitionKey.length
      return RANDOM_POOL[n % RANDOM_POOL.length]
    }
    return effect
  }, [effect, transitionKey])

  if (resolved === 'none') return <>{children}</>

  return (
    <div key={String(transitionKey)} className={`qtrans qtrans-${resolved}`}>
      {children}
    </div>
  )
}
