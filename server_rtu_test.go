package modbus

import (
	"net"
	"testing"
	"time"
)

func TestRTUServerReadWriteAndException(t *testing.T) {
	serverLink, clientLink := net.Pipe()
	defer clientLink.Close()

	th := &tcpTestHandler{}
	server, err := NewServer(&ServerConfiguration{
		URL: "rtu://virtual-device",
		serialLinkFactory: func(conf *serialPortConfig) (rtuLink, error) {
			return serverLink, nil
		},
	}, th)
	if err != nil {
		t.Fatalf("failed to create server: %v", err)
	}
	if err = server.Start(); err != nil {
		t.Fatalf("failed to start server: %v", err)
	}
	defer server.Stop()

	rt := newRTUTransport(clientLink, "virtual-device", 19200, 200*time.Millisecond, nil)

	// Write a single coil then read it back.
	_, err = rt.ExecuteRequest(&pdu{
		unitId:       9,
		functionCode: fcWriteSingleCoil,
		payload:      []byte{0x00, 0x04, 0xff, 0x00},
	})
	if err != nil {
		t.Fatalf("write single coil failed: %v", err)
	}

	res, err := rt.ExecuteRequest(&pdu{
		unitId:       9,
		functionCode: fcReadCoils,
		payload:      []byte{0x00, 0x04, 0x00, 0x01},
	})
	if err != nil {
		t.Fatalf("read coils failed: %v", err)
	}
	if len(res.payload) != 2 || res.payload[0] != 0x01 || (res.payload[1]&0x01) != 0x01 {
		t.Fatalf("unexpected read-coils response payload: %#v", res.payload)
	}

	// Unit id mismatch should be mapped to illegal function.
	res, err = rt.ExecuteRequest(&pdu{
		unitId:       7,
		functionCode: fcReadHoldingRegisters,
		payload:      []byte{0x00, 0x00, 0x00, 0x01},
	})
	if err != nil {
		t.Fatalf("unexpected exception read error: %v", err)
	}
	if res.functionCode != (0x80|fcReadHoldingRegisters) || len(res.payload) != 1 || res.payload[0] != exIllegalFunction {
		t.Fatalf("unexpected exception response: %#v", res)
	}
}
