import { AssistantPanel } from '../components/AssistantPanel/AssistantPanel'
import styles from './Page.module.css'

export function AssistantPage() {
  return (
    <>
      <header className={styles.header}>
        <h1>Assistente de IA</h1>
        <p>Consultas com fontes citadas, a partir das suas notas e documentos.</p>
      </header>
      <AssistantPanel />
    </>
  )
}
