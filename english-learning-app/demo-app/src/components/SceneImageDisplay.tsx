interface Props {
  imagePath: string
  alt: string
}

export function SceneImageDisplay({ imagePath, alt }: Props) {
  return (
    <div className="scene-image-wrap">
      <img
        src={imagePath}
        alt={alt}
        className="scene-image"
        loading="eager"
        onError={(e) => {
          ;(e.target as HTMLImageElement).style.display = 'none'
        }}
      />
      <div className="scene-image-caption">{alt}</div>
    </div>
  )
}
