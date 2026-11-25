import styles from './ColorPicker.module.css'

const PALETTE = [
  { name: 'Azul', value: '#6d7cff' },
  { name: 'Verde', value: '#4fc38a' },
  { name: 'Âmbar', value: '#e0a94a' },
  { name: 'Vermelho', value: '#ef6a6a' },
  { name: 'Rosa', value: '#e07ab8' },
  { name: 'Ciano', value: '#4fb8d6' },
  { name: 'Cinza', value: '#8b8f9a' },
]

interface ColorPickerProps {
  legend: string
  value: string | null
  onChange: (value: string | null) => void
}

export function ColorPicker({ legend, value, onChange }: ColorPickerProps) {
  return (
    <fieldset className={styles.group}>
      <legend>{legend}</legend>
      <div className={styles.row}>
        <label className={styles.option}>
          <input type="radio" name={legend} checked={value === null} onChange={() => onChange(null)} />
          <span className={`${styles.swatch} ${styles.none}`}>∅</span>
          <span className={styles.srOnly}>Sem cor</span>
        </label>
        {PALETTE.map((c) => (
          <label key={c.value} className={styles.option}>
            <input type="radio" name={legend} checked={value === c.value} onChange={() => onChange(c.value)} />
            <span className={styles.swatch} style={{ background: c.value }} />
            <span className={styles.srOnly}>{c.name}</span>
          </label>
        ))}
      </div>
    </fieldset>
  )
}
