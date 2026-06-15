export default function LoadingSpinner({ message = 'Loading…' }) {
  return (
    <div className="loading-state">
      <div className="spinner" />
      <p>{message}</p>
    </div>
  )
}
