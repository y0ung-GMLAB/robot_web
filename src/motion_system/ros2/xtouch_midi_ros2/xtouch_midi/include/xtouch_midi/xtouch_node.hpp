#ifndef XTOUCH_MIDI_XTOUCH_NODE_HPP_
#define XTOUCH_MIDI_XTOUCH_NODE_HPP_

#include <array>
#include <chrono>
#include <cstdint>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

#include <rtmidi/RtMidi.h>

#include <midi_msgs/msg/midi.hpp>
#include <rclcpp/rclcpp.hpp>

namespace xtouch_midi
{

class XTouchNode : public rclcpp::Node
{
public:
  using MidiMsg = midi_msgs::msg::Midi;

  explicit XTouchNode(const rclcpp::NodeOptions & options = rclcpp::NodeOptions());
  ~XTouchNode() override;

private:
  template<typename Port>
  void open_matching_port(Port & port, const char * direction);

  static void midi_trampoline(
    double timestamp,
    std::vector<unsigned char> * msg,
    void * user_data);

  void on_midi(const std::vector<unsigned char> & bytes);
  void set_fader_value(uint8_t ch, int32_t value);
  void publish_state();
  void tick_debounce();
  void send_fader_pitch_bend(uint8_t ch, int32_t value);
  void send_button_led(uint8_t note, bool on);
  void send_display_text(uint8_t offset, const std::string & text);
  void send_channel_dial_display(uint8_t ch, int32_t value);
  bool toggle_button_state(uint8_t note, bool pressed);
  int32_t encoder_delta(uint8_t value) const;

  std::unique_ptr<RtMidiIn> midi_in_;
  std::unique_ptr<RtMidiOut> midi_out_;

  rclcpp::Publisher<MidiMsg>::SharedPtr midi_pub_;
  bool encoder_relative_mode_{true};
  bool button_led_feedback_{true};
  bool display_feedback_{true};
  uint8_t display_device_id_{0x15};

  std::mutex state_mutex_;
  std::array<bool, 8> btn0_{};
  std::array<bool, 8> btn1_{};
  std::array<bool, 8> btn2_{};
  std::array<bool, 8> btn3_{};
  std::array<bool, 8> touch_{};
  std::array<bool, 8> btn3_requires_fader_update_{};
  std::array<int32_t, 8> channel_{};
  std::array<int32_t, 8> dial_{};
  std::array<std::optional<std::chrono::steady_clock::time_point>, 8>
    debounce_deadline_{};

  rclcpp::TimerBase::SharedPtr publish_tick_;
  rclcpp::TimerBase::SharedPtr debounce_tick_;
};

}  // namespace xtouch_midi

#endif  // XTOUCH_MIDI_XTOUCH_NODE_HPP_
