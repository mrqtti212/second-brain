import { ResourceManager } from '../features/organization/ResourceManager'
import { categoriesApi, projectsApi, tagsApi } from '../services/api'
import styles from './Page.module.css'

export function OrganizePage() {
  return (
    <>
      <header className={styles.header}>
        <h1>Organizar</h1>
        <p>Categorias, projetos e etiquetas usados para classificar suas notas. Excluir um deles não exclui as notas.</p>
      </header>
      <div className={styles.stack}>
        <ResourceManager
          labels={{ title: 'Categorias', singular: 'categoria', article: 'a', empty: 'Nenhuma categoria criada.', deleteEffect: 'As notas continuam existindo, apenas sem categoria.' }}
          api={categoriesApi}
          withColor
          withDescription
        />
        <ResourceManager
          labels={{ title: 'Projetos', singular: 'projeto', article: 'o', empty: 'Nenhum projeto criado.', deleteEffect: 'As notas continuam existindo, apenas sem projeto.' }}
          api={projectsApi}
          withDescription
        />
        <ResourceManager
          labels={{ title: 'Etiquetas', singular: 'etiqueta', article: 'a', empty: 'Nenhuma etiqueta criada.', deleteEffect: 'As notas continuam existindo, apenas sem esta etiqueta.' }}
          api={tagsApi}
          withColor
        />
      </div>
    </>
  )
}
