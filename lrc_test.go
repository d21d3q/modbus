package modbus

import "testing"

func TestComputeAndVerifyLRC(t *testing.T) {
	tests := []struct {
		name string
		in   []byte
		lrc  byte
	}{
		{
			name: "read holding registers example",
			in:   []byte{0x01, 0x03, 0x00, 0x13, 0x00, 0x0a},
			lrc:  0xdf,
		},
		{
			name: "short payload",
			in:   []byte{0x10, 0x11, 0x12},
			lrc:  0xcd,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := computeLRC(tt.in)
			if got != tt.lrc {
				t.Fatalf("computeLRC(%x) = 0x%02x, want 0x%02x", tt.in, got, tt.lrc)
			}

			if !verifyLRC(tt.in, tt.lrc) {
				t.Fatalf("verifyLRC(%x, 0x%02x) returned false", tt.in, tt.lrc)
			}
		})
	}
}
