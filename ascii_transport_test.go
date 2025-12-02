package modbus

import (
	"net"
	"testing"
	"time"
)

func TestAssembleASCIIFrame(t *testing.T) {
	at := &asciiTransport{}

	frame := at.assembleASCIIFrame(&pdu{
		unitId:       0x33,
		functionCode: 0x11,
		payload:      []byte{0x22, 0x33},
	})

	expected := []byte(":3311223367\r\n")
	if string(frame) != string(expected) {
		t.Fatalf("unexpected frame: got %q, want %q", frame, expected)
	}
}

func TestASCIITransportReadASCIIFrame(t *testing.T) {
	p1, p2 := net.Pipe()
	defer p1.Close()
	defer p2.Close()

	at := newASCIITransport(p2, "", 9600, 50*time.Millisecond, nil)

	frame := []byte(":31030411223362\r\n")

	go func() {
		p1.Write(frame)
	}()

	// set a deadline so the read does not hang in tests
	at.link.SetDeadline(time.Now().Add(100 * time.Millisecond))

	res, err := at.readASCIIFrame()
	if err != nil {
		t.Fatalf("readASCIIFrame() failed: %v", err)
	}

	if res.unitId != 0x31 {
		t.Fatalf("unexpected unit id: got 0x%02x, want 0x31", res.unitId)
	}
	if res.functionCode != 0x03 {
		t.Fatalf("unexpected function code: got 0x%02x, want 0x03", res.functionCode)
	}
	if len(res.payload) != 4 {
		t.Fatalf("unexpected payload length: got %v, want 4", len(res.payload))
	}
	for i, b := range []byte{0x04, 0x11, 0x22, 0x33} {
		if res.payload[i] != b {
			t.Fatalf("unexpected payload byte at %d: got 0x%02x, want 0x%02x", i, res.payload[i], b)
		}
	}
}

func TestASCIITransportReadASCIIFrameBadLRC(t *testing.T) {
	p1, p2 := net.Pipe()
	defer p1.Close()
	defer p2.Close()

	at := newASCIITransport(p2, "", 9600, 50*time.Millisecond, nil)

	badFrame := []byte(":31030411223300\r\n")

	go func() {
		p1.Write(badFrame)
	}()

	at.link.SetDeadline(time.Now().Add(100 * time.Millisecond))

	_, err := at.readASCIIFrame()
	if err != ErrBadLRC {
		t.Fatalf("expected ErrBadLRC, got %v", err)
	}
}

func TestASCIITransportReadASCIIFrameShort(t *testing.T) {
	p1, p2 := net.Pipe()
	defer p1.Close()
	defer p2.Close()

	at := newASCIITransport(p2, "", 9600, 50*time.Millisecond, nil)

	shortFrame := []byte(":33\r\n")

	go func() {
		p1.Write(shortFrame)
	}()

	at.link.SetDeadline(time.Now().Add(100 * time.Millisecond))

	_, err := at.readASCIIFrame()
	if err != ErrShortFrame {
		t.Fatalf("expected ErrShortFrame, got %v", err)
	}
}
