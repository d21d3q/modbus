package modbus

import (
	"testing"
	"time"
)

func TestNewClientASCII(t *testing.T) {
	client, err := NewClient(&ClientConfiguration{
		URL: "ascii:///dev/ttyS0",
	})
	if err != nil {
		t.Fatalf("NewClient() returned error: %v", err)
	}

	if client.transportType != modbusASCII {
		t.Fatalf("unexpected transport type: got %v, want %v", client.transportType, modbusASCII)
	}

	if client.conf.Speed != 19200 {
		t.Fatalf("expected default speed 19200, got %v", client.conf.Speed)
	}

	if client.conf.Timeout != 300*time.Millisecond {
		t.Fatalf("expected default timeout 300ms, got %v", client.conf.Timeout)
	}

	if client.conf.DataBits != 8 {
		t.Fatalf("expected default data bits 8, got %v", client.conf.DataBits)
	}

	if client.conf.StopBits != 2 {
		t.Fatalf("expected default stop bits 2, got %v", client.conf.StopBits)
	}
}

func TestNewClientASCIIOverTCPSchemeUnsupported(t *testing.T) {
	_, err := NewClient(&ClientConfiguration{
		URL: "asciiovertcp://localhost:502",
	})
	if err == nil {
		t.Fatalf("expected configuration error for ascii over tcp")
	}
}
