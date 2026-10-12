/** 실행 OS 감지 — Electron은 preload가 준 process.platform, 브라우저(npm run web / OBS)는 navigator에서 읽는다 */
export type Os = 'mac' | 'win' | 'other'

interface NavigatorWithUAData extends Navigator {
  userAgentData?: { platform?: string }
}

export function detectOs(): Os {
  const electron = window.mingo?.platform
  if (electron === 'darwin') return 'mac'
  if (electron === 'win32') return 'win'
  if (electron) return 'other'
  const nav = navigator as NavigatorWithUAData
  const raw = (nav.userAgentData?.platform ?? navigator.platform ?? '').toLowerCase()
  if (raw.includes('mac')) return 'mac'
  if (raw.includes('win')) return 'win'
  return 'other'
}

export const os: Os = detectOs()
