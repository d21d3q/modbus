package main

import (
	"flag"
	"log"
	"os"
	"os/signal"
	"sync"
	"syscall"

	"github.com/simonvetter/modbus"
)

type harnessHandler struct {
	lock     sync.Mutex
	unitID   uint8
	coils    []bool
	discrete []bool
	holding  []uint16
	input    []uint16
}

func newHarnessHandler(unitID uint8) *harnessHandler {
	holdingBase := []uint16{0x1111, 0x2222, 0x1234, 0xabcd, 0x0000, 0x7fff, 0x8000}
	holdingExtra := make([]uint16, 130)
	for i := range holdingExtra {
		holdingExtra[i] = 0x1000 + uint16(i)
	}
	holding := append(holdingBase, holdingExtra...)

	return &harnessHandler{
		unitID:   unitID,
		coils:    []bool{true, false, true, true, false, false, true, false},
		discrete: []bool{false, true, true, false, true, false, false, true},
		holding:  holding,
		input:    []uint16{0x9999, 0xaaaa, 0xbbbb, 0xcccc},
	}
}

func (h *harnessHandler) HandleCoils(req *modbus.CoilsRequest) (res []bool, err error) {
	if req.UnitId != h.unitID {
		return nil, modbus.ErrIllegalFunction
	}

	h.lock.Lock()
	defer h.lock.Unlock()

	if int(req.Addr)+int(req.Quantity) > len(h.coils) {
		return nil, modbus.ErrIllegalDataAddress
	}

	for i := 0; i < int(req.Quantity); i++ {
		if req.IsWrite {
			h.coils[int(req.Addr)+i] = req.Args[i]
		}
		res = append(res, h.coils[int(req.Addr)+i])
	}

	return
}

func (h *harnessHandler) HandleDiscreteInputs(req *modbus.DiscreteInputsRequest) (res []bool, err error) {
	if req.UnitId != h.unitID {
		return nil, modbus.ErrIllegalFunction
	}

	h.lock.Lock()
	defer h.lock.Unlock()

	if int(req.Addr)+int(req.Quantity) > len(h.discrete) {
		return nil, modbus.ErrIllegalDataAddress
	}
	for i := 0; i < int(req.Quantity); i++ {
		res = append(res, h.discrete[int(req.Addr)+i])
	}

	return
}

func (h *harnessHandler) HandleHoldingRegisters(req *modbus.HoldingRegistersRequest) (res []uint16, err error) {
	if req.UnitId != h.unitID {
		return nil, modbus.ErrIllegalFunction
	}

	h.lock.Lock()
	defer h.lock.Unlock()

	if int(req.Addr)+int(req.Quantity) > len(h.holding) {
		return nil, modbus.ErrIllegalDataAddress
	}
	for i := 0; i < int(req.Quantity); i++ {
		if req.IsWrite {
			h.holding[int(req.Addr)+i] = req.Args[i]
		}
		res = append(res, h.holding[int(req.Addr)+i])
	}

	return
}

func (h *harnessHandler) HandleInputRegisters(req *modbus.InputRegistersRequest) (res []uint16, err error) {
	if req.UnitId != h.unitID {
		return nil, modbus.ErrIllegalFunction
	}

	h.lock.Lock()
	defer h.lock.Unlock()

	if int(req.Addr)+int(req.Quantity) > len(h.input) {
		return nil, modbus.ErrIllegalDataAddress
	}
	for i := 0; i < int(req.Quantity); i++ {
		res = append(res, h.input[int(req.Addr)+i])
	}

	return
}

func main() {
	mode := flag.String("mode", "tcp", "server mode: tcp|rtu|ascii")
	listen := flag.String("listen", "127.0.0.1:1502", "listen address for tcp mode")
	serial := flag.String("serial", "", "serial device path for rtu/ascii modes")
	unitID := flag.Uint("unit-id", 1, "unit id accepted by the harness")
	flag.Parse()

	var url string
	switch *mode {
	case "tcp":
		url = "tcp://" + *listen
	case "rtu":
		if *serial == "" {
			log.Fatal("--serial is required for rtu mode")
		}
		url = "rtu://" + *serial
	case "ascii":
		if *serial == "" {
			log.Fatal("--serial is required for ascii mode")
		}
		url = "ascii://" + *serial
	default:
		log.Fatalf("unsupported mode: %s", *mode)
	}

	handler := newHarnessHandler(uint8(*unitID))
	server, err := modbus.NewServer(&modbus.ServerConfiguration{
		URL:      url,
		Speed:    19200,
		DataBits: 8,
		Parity:   modbus.PARITY_NONE,
		StopBits: 2,
	}, handler)
	if err != nil {
		log.Fatalf("new server failed: %v", err)
	}
	if err = server.Start(); err != nil {
		log.Fatalf("start server failed: %v", err)
	}
	defer server.Stop()

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
	<-sigCh
}
