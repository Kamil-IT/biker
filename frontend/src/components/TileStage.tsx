import { useState, type ReactNode } from 'react'

const DEFAULT_STAGE_BG = '#FFFFFF'
const EMPTY_STAGE_BG = '#E6DED1'

interface TileStageProps {
  photo: string | null
  // The photo's edge colour (bike photos carry one); white when unknown.
  bg?: string | null
  alt: string
  // The drawing and the text of the empty stage (no photo, or it failed to load twice).
  art: ReactNode
  emptyText: string
  // Overlays: the bike tile's rating plate and bar, the part tile's "Nowe z AI" badge.
  children?: ReactNode
}

// The 4:3 photo stage of a "Kadr" result tile, shared by the bike tiles (ResultCard) and the
// parts tiles (PartCard): the photo is contained, never cropped, on its own edge colour. A photo
// that fails to load is re-requested once (the <img> remounts, same URL); only the second error
// shows the empty stage.
export default function TileStage({ photo, bg, alt, art, emptyText, children }: TileStageProps) {
  // The URL that failed to load: a different photo later gets a fresh try.
  const [failedPhoto, setFailedPhoto] = useState<string | null>(null)
  // One automatic retry per URL: the first error remounts the <img> (same URL), the second gives up.
  const [retry, setRetry] = useState<{ url: string | null; count: number }>({ url: null, count: 0 })
  const retries = retry.url === photo ? retry.count : 0
  const handlePhotoError = () => {
    if (photo == null) return
    if (retries < 1) setRetry({ url: photo, count: retries + 1 })
    else setFailedPhoto(photo)
  }
  const showPhoto = photo != null && photo !== failedPhoto

  return (
    <div
      className={`relative aspect-[4/3] overflow-hidden ${showPhoto ? '' : 'grid place-items-center'}`}
      style={{ background: showPhoto ? (bg ?? DEFAULT_STAGE_BG) : EMPTY_STAGE_BG }}
    >
      {showPhoto ? (
        <img
          key={retries}
          src={photo}
          alt={alt}
          loading="lazy"
          decoding="async"
          className="w-full h-full object-contain block"
          onError={handlePhotoError}
        />
      ) : (
        <div className="grid justify-items-center gap-2.5 p-4 text-center">
          {art}
          <p className="font-body text-[13px] leading-snug text-ink max-w-60">{emptyText}</p>
        </div>
      )}
      {children}
    </div>
  )
}
