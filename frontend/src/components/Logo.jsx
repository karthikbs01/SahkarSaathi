export default function Logo({ className = '' }) {
  return <img className={`brand-logo${className ? ` ${className}` : ''}`}
    src="/assets/sahkaar-saathi-logo.png" alt="Sahkaar Saathi" />
}
