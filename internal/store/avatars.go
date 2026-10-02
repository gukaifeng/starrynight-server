package store

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"github.com/jackc/pgx/v5"
	"golang.org/x/image/draw"
	"image"
	"image/color"
	"image/jpeg"
	_ "image/png"
)

type AccountAvatar struct {
	SHA256      string `json:"sha256"`
	ContentType string `json:"content_type"`
	Image       []byte `json:"image"`
}

func normalizeAvatar(input []byte) (AccountAvatar, error) {
	if len(input) == 0 || len(input) > 512*1024 {
		return AccountAvatar{}, invalid("avatar input exceeds 512 KiB")
	}
	config, format, err := image.DecodeConfig(bytes.NewReader(input))
	if err != nil || (format != "jpeg" && format != "png") || config.Width < 1 || config.Height < 1 || config.Width > 4096 || config.Height > 4096 || int64(config.Width)*int64(config.Height) > 4*1024*1024 {
		return AccountAvatar{}, invalid("invalid avatar dimensions or format")
	}
	source, _, err := image.Decode(bytes.NewReader(input))
	if err != nil {
		return AccountAvatar{}, invalid("invalid image")
	}
	bounds := source.Bounds()
	side := min(bounds.Dx(), bounds.Dy())
	center := image.Rect(bounds.Min.X+(bounds.Dx()-side)/2, bounds.Min.Y+(bounds.Dy()-side)/2, bounds.Min.X+(bounds.Dx()-side)/2+side, bounds.Min.Y+(bounds.Dy()-side)/2+side)
	target := image.NewRGBA(image.Rect(0, 0, 256, 256))
	draw.Draw(target, target.Bounds(), image.NewUniform(color.RGBA{18, 23, 36, 255}), image.Point{}, draw.Src)
	draw.CatmullRom.Scale(target, target.Bounds(), source, center, draw.Over, nil)
	var result bytes.Buffer
	if err = jpeg.Encode(&result, target, &jpeg.Options{Quality: 88}); err != nil {
		return AccountAvatar{}, err
	}
	if result.Len() > 128*1024 {
		return AccountAvatar{}, invalid("avatar output too large")
	}
	sum := sha256.Sum256(result.Bytes())
	return AccountAvatar{hex.EncodeToString(sum[:]), "image/jpeg", result.Bytes()}, nil
}

func (s *Store) Avatar(ctx context.Context, id string) (AccountAvatar, error) {
	var out AccountAvatar
	err := s.Pool.QueryRow(ctx, `SELECT a.sha256,a.content_type,a.image FROM account_avatars a JOIN users u ON u.id=a.user_id WHERE a.user_id=$1 AND u.profile->>'avatar'='upload:'||a.sha256`, id).Scan(&out.SHA256, &out.ContentType, &out.Image)
	return out, classify(err)
}

func (s *Store) ReplaceAvatar(ctx context.Context, id string, expected int64, input []byte) (Document, error) {
	avatar, err := normalizeAvatar(input)
	if err != nil {
		return Document{}, err
	}
	var out Document
	err = s.write(ctx, id, func(tx pgx.Tx) error {
		var profile map[string]any
		var version int64
		if e := tx.QueryRow(ctx, "SELECT profile,version FROM users WHERE id=$1", id).Scan(&profile, &version); e != nil {
			return e
		}
		if version != expected {
			return ErrConflict
		}
		_, e := tx.Exec(ctx, `INSERT INTO account_avatars(user_id,sha256,content_type,image) VALUES($1,$2,$3,$4) ON CONFLICT(user_id) DO UPDATE SET sha256=EXCLUDED.sha256,content_type=EXCLUDED.content_type,image=EXCLUDED.image,updated_at=now()`, id, avatar.SHA256, avatar.ContentType, avatar.Image)
		if e != nil {
			return e
		}
		profile["avatar"] = "upload:" + avatar.SHA256
		if _, e = tx.Exec(ctx, "UPDATE users SET profile=$2,version=version+1 WHERE id=$1", id, profile); e != nil {
			return e
		}
		out = Document{1, version + 1, profile}
		return event(ctx, tx, id, "profile", id, false, out)
	})
	return out, err
}
