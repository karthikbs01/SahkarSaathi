// Renders backend answer text as safe React elements only — paragraphs, numbered
// steps, bullet points and **bold** emphasis. Never uses dangerouslySetInnerHTML,
// so the backend can only ever produce plain text nodes here, never markup.

function renderInline(line, keyPrefix) {
  const parts = line.split(/(\*\*[^*]+\*\*)/g).filter((part) => part !== '')
  return parts.map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return <strong key={`${keyPrefix}-${index}`}>{part.slice(2, -2)}</strong>
    }
    return <span key={`${keyPrefix}-${index}`}>{part}</span>
  })
}

function isOrderedListBlock(lines) {
  return lines.every((line) => /^\d+\.\s+/.test(line.trim()))
}

function isBulletListBlock(lines) {
  return lines.every((line) => /^[-*]\s+/.test(line.trim()))
}

export default function FormattedAnswer({ text }) {
  if (!text) return null

  const blocks = text.trim().split(/\n\s*\n/)

  return (
    <div className="formatted-answer">
      {blocks.map((block, blockIndex) => {
        const lines = block.split('\n').map((line) => line.trim()).filter(Boolean)
        if (lines.length === 0) return null

        if (isOrderedListBlock(lines)) {
          return (
            <ol key={blockIndex} className="formatted-answer__list">
              {lines.map((line, lineIndex) => (
                <li key={lineIndex}>
                  {renderInline(line.replace(/^\d+\.\s+/, ''), `${blockIndex}-${lineIndex}`)}
                </li>
              ))}
            </ol>
          )
        }

        if (isBulletListBlock(lines)) {
          return (
            <ul key={blockIndex} className="formatted-answer__list">
              {lines.map((line, lineIndex) => (
                <li key={lineIndex}>
                  {renderInline(line.replace(/^[-*]\s+/, ''), `${blockIndex}-${lineIndex}`)}
                </li>
              ))}
            </ul>
          )
        }

        return (
          <p key={blockIndex} className="formatted-answer__paragraph">
            {lines.map((line, lineIndex) => (
              <span key={lineIndex}>
                {renderInline(line, `${blockIndex}-${lineIndex}`)}
                {lineIndex < lines.length - 1 && <br />}
              </span>
            ))}
          </p>
        )
      })}
    </div>
  )
}
