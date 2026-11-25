// O backend marca os termos encontrados entre U+E000 e U+E001.
// Montamos <mark> por split, sem interpretar o texto como HTML.
const START = ''
const END = ''

export function Highlight({ text }: { text: string }) {
  const parts = text.split(new RegExp(`(${START}[^${END}]*${END})`))
  return (
    <>
      {parts.map((part, i) =>
        part.startsWith(START) ? (
          <mark key={i}>{part.slice(1, -1)}</mark>
        ) : (
          <span key={i}>{part.replaceAll(START, '').replaceAll(END, '')}</span>
        ),
      )}
    </>
  )
}
