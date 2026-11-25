import { Sparkles } from 'lucide-react'
import { Badge } from '../Badge/Badge'
import styles from './AssistantPanel.module.css'

// Espaço reservado. Nenhuma IA está conectada nesta fase.
export function AssistantPanel() {
  return (
    <section className={styles.panel} aria-labelledby="assistant-heading">
      <div className={styles.head}>
        <span className={styles.icon}>
          <Sparkles size={18} aria-hidden />
        </span>
        <h2 id="assistant-heading">Assistente de IA</h2>
        <Badge tone="accent">Em breve</Badge>
      </div>
      <p className={styles.text}>
        Aqui você poderá conversar com suas notas e documentos, com as fontes de cada resposta
        visíveis. Depende de busca semântica e de um provedor de IA, previstos para as próximas fases.
      </p>
      <div className={styles.input}>
        <input disabled placeholder="Pergunte algo sobre seus conteúdos…" aria-label="Pergunta ao assistente (indisponível)" />
        <button type="button" disabled>Enviar</button>
      </div>
    </section>
  )
}
